"""行情数据：读取本地 CSV，换算成 招行中间价（人民币/克），以及从 Twelve Data 分段下载。"""

from __future__ import annotations

import bisect
import csv
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

GRAMS_PER_OZ = 31.1034768


@dataclass(frozen=True)
class Bar:
    date: dt.date
    open: float
    high: float
    low: float
    close: float


def _read_csv(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_fx(path: str) -> list[tuple[dt.date, float]]:
    rows = [(dt.date.fromisoformat(r["date"]), float(r["close"])) for r in _read_csv(path)]
    rows.sort()
    return rows


def fx_at(fx: list[tuple[dt.date, float]], day: dt.date) -> float:
    """线性插值的美元兑人民币汇率（日线或周线都可以）。"""
    dates = [d for d, _ in fx]
    i = bisect.bisect_left(dates, day)
    if i == 0:
        return fx[0][1]
    if i >= len(fx):
        return fx[-1][1]
    (d0, v0), (d1, v1) = fx[i - 1], fx[i]
    if d1 == d0:
        return v1
    return v0 + (v1 - v0) * (day - d0).days / (d1 - d0).days


def load_bars(gold_csv: str, fx_csv: str, premium: float = 0.0, ref_price: float | None = None) -> list[Bar]:
    """读取 XAU/USD 日线并换算为人民币/克中间价。

    - 去掉周六周日（数据源会返回近似平盘的周末 K 线）
    - 加上招行相对国际换算价的溢价 premium；给了 ref_price 时按金价比例缩放溢价
    """
    fx = load_fx(fx_csv)
    bars = []
    for r in _read_csv(gold_csv):
        day = dt.date.fromisoformat(r["date"])
        if day.weekday() >= 5:
            continue
        k = fx_at(fx, day) / GRAMS_PER_OZ
        raw = [float(r[x]) * k for x in ("open", "high", "low", "close")]
        prem = premium * (raw[3] / ref_price if ref_price else 1.0)
        o, h, l, c = (v + prem for v in raw)
        bars.append(Bar(day, o, max(h, o, c), min(l, o, c), c))
    bars.sort(key=lambda b: b.date)
    return bars


# ---- 招行交易时段日线 ----

def session_bars_from_hourly(rows: list[dict], start: str = "09:30", end: str = "24:00") -> list[dict]:
    """把北京时间的小时线合成为"招行交易时段日线"（默认 9:30~24:00，周一到周五）。

    小时线以整点开始，所以取所有与交易时段有重叠的小时（9:00 那根也算进来，
    最高最低价会略微多包含 9:00~9:30 的行情，对止损判断是偏保守的）。
    rows: [{"datetime": "YYYY-MM-DD HH:MM:SS", open, high, low, close}]，时区为北京时间。
    """
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    start_min, end_min = sh * 60 + sm, eh * 60 + em
    by_day: dict[str, list[dict]] = {}
    for r in sorted(rows, key=lambda r: r["datetime"]):
        ts = dt.datetime.fromisoformat(r["datetime"])
        if ts.weekday() >= 5:
            continue
        m0 = ts.hour * 60 + ts.minute
        if m0 + 60 <= start_min or m0 >= end_min:     # 与交易时段没有重叠
            continue
        by_day.setdefault(ts.date().isoformat(), []).append(r)
    out = []
    for day, rs in sorted(by_day.items()):
        out.append({
            "date": day,
            "open": float(rs[0]["open"]),
            "high": max(float(r["high"]) for r in rs),
            "low": min(float(r["low"]) for r in rs),
            "close": float(rs[-1]["close"]),
        })
    return out


# ---- Twelve Data 下载（需要环境变量 TWELVE_DATA_API_KEY）----

API = "https://api.twelvedata.com/time_series"
PAGE = 5000


def _request(params: dict) -> dict:
    with urllib.request.urlopen(f"{API}?{urllib.parse.urlencode(params)}", timeout=60) as resp:
        return json.load(resp)


def fetch_series(symbol: str, interval: str, start: str, end: str, api_key: str,
                 tz: str = "UTC", pause: float = 8.0, request=_request) -> list[dict]:
    """分段下载：一次最多 5000 条，从最新往回翻页，直到覆盖 start。返回按时间升序、去重后的数据。"""
    seen: dict[str, dict] = {}
    cur_end = end
    while True:
        payload = request({
            "symbol": symbol, "interval": interval, "start_date": start, "end_date": cur_end,
            "outputsize": PAGE, "timezone": tz, "order": "desc", "apikey": api_key,
        })
        if payload.get("status") != "ok":
            if payload.get("code") == 400 and "No data" in str(payload.get("message", "")):
                break
            raise RuntimeError(f"Twelve Data 返回错误: {payload.get('message', payload)}")
        values = payload["values"]
        new = [v for v in values if v["datetime"] not in seen]
        for v in new:
            seen[v["datetime"]] = v
        oldest = min(v["datetime"] for v in values)
        if len(values) < PAGE or not new or oldest[:10] <= start:
            break
        cur_end = oldest              # end_date 是开区间端点附近，重复的那条会被去重
        if pause:
            time.sleep(pause)         # 免费套餐每分钟 8 次请求
    return [seen[k] for k in sorted(seen)]


def _write_ohlc(path: str, rows: list[dict], date_key: str = "date") -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close"])
        for r in rows:
            w.writerow([r[date_key][:10], r["open"], r["high"], r["low"], r["close"]])


def update_data(data_cfg: dict, start: str, end: str, hourly_start: str | None, pause: float = 8.0) -> None:
    key = os.environ.get("TWELVE_DATA_API_KEY")
    if not key:
        raise SystemExit("请先设置环境变量 TWELVE_DATA_API_KEY")

    gold = fetch_series("XAU/USD", "1day", start, end, key, pause=pause)
    _write_ohlc(data_cfg["gold_csv"], gold, "datetime")
    print(f"XAU/USD 日线 {len(gold)} 条 → {data_cfg['gold_csv']}")

    fx = fetch_series("USD/CNY", "1day", start, end, key, pause=pause)
    with open(data_cfg["fx_csv"], "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "close"])
        for v in fx:
            w.writerow([v["datetime"][:10], v["close"]])
    print(f"USD/CNY 日线 {len(fx)} 条 → {data_cfg['fx_csv']}")

    if hourly_start:
        hourly = fetch_series("XAU/USD", "1h", hourly_start, end, key, tz="Asia/Shanghai", pause=pause)
        session = session_bars_from_hourly(hourly, *data_cfg.get("session", "09:30-24:00").split("-"))
        _write_ohlc(data_cfg["session_csv"], session)
        print(f"XAU/USD 小时线 {len(hourly)} 条 → 招行时段日线 {len(session)} 条 → {data_cfg['session_csv']}")
