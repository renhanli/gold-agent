"""方向 A：趋势择时持有。

和 backtest.py 的"每笔风险 1%"不同，这里每天给出一个目标仓位（0~100% 的权益买成黄金），
只有目标仓位变化时才买卖，尽量少付点差。

成交假设与短线回测一致：第 i 天收盘算目标仓位，第 i+1 天开盘按买入价/卖出价成交。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import indicators as ind
from .backtest import cost_scale
from .data import Bar

TRADING_DAYS = 252


# ---- 择时规则：返回每天收盘后的目标仓位（0~1）----

def sma_filter(bars: list[Bar], n: int = 200, band: float = 0.01) -> list[float]:
    """收盘价高于 n 日均线 (1+band) 时满仓，低于 (1-band) 时空仓，中间维持原状态（防止来回打脸）。"""
    closes = [b.close for b in bars]
    ma = ind.sma(closes, n)
    out, state = [], 0.0
    for c, m in zip(closes, ma):
        if m is not None:
            if c > m * (1 + band):
                state = 1.0
            elif c < m * (1 - band):
                state = 0.0
        out.append(state)
    return out


def sma_cross(bars: list[Bar], fast: int = 50, slow: int = 200) -> list[float]:
    """快线在慢线上方时满仓（"金叉"持有，"死叉"清仓）。"""
    closes = [b.close for b in bars]
    f, s = ind.sma(closes, fast), ind.sma(closes, slow)
    return [1.0 if a is not None and b is not None and a > b else 0.0 for a, b in zip(f, s)]


def donchian(bars: list[Bar], entry: int = 100, exit: int = 50) -> list[float]:
    """收盘创 entry 日新高时买入，收盘跌破 exit 日最低价时卖出（海龟法则的长周期版本）。"""
    hh = ind.highest([b.close for b in bars], entry)
    ll = [None if i < exit else min(b.close for b in bars[i - exit:i]) for i in range(len(bars))]
    out, state = [], 0.0
    for i, b in enumerate(bars):
        if hh[i] is not None and b.close > hh[i]:
            state = 1.0
        elif ll[i] is not None and b.close < ll[i]:
            state = 0.0
        out.append(state)
    return out


def momentum(bars: list[Bar], lookback: int = 252, monthly: bool = True) -> list[float]:
    """过去 lookback 个交易日涨了就持有，跌了就空仓；monthly=True 时只在每月最后一个交易日调整。"""
    out, state = [], 0.0
    for i, b in enumerate(bars):
        month_end = i == len(bars) - 1 or bars[i + 1].date.month != b.date.month
        if i >= lookback and (month_end or not monthly):
            state = 1.0 if b.close > bars[i - lookback].close else 0.0
        out.append(state)
    return out


def vol_target(bars: list[Bar], base: list[float], target: float = 0.12, window: int = 60,
               cap: float = 1.0) -> list[float]:
    """在择时信号基础上按波动率调仓：仓位 = 目标年化波动 ÷ 近期实际波动（上限 cap）。"""
    rets = [0.0] + [bars[i].close / bars[i - 1].close - 1 for i in range(1, len(bars))]
    out = []
    for i, w in enumerate(base):
        if i < window or w == 0:
            out.append(0.0 if w == 0 else w)
            continue
        r = rets[i - window + 1:i + 1]
        m = sum(r) / window
        vol = math.sqrt(sum((x - m) ** 2 for x in r) / (window - 1)) * math.sqrt(TRADING_DAYS)
        out.append(w * min(cap, target / vol) if vol > 0 else w)
    return out


# ---- 回测引擎 ----

@dataclass
class AllocResult:
    name: str
    bars: list[Bar]
    capital: float
    equity: list[float]
    weights: list[float]                 # 每天收盘后的实际持仓比例
    trades: int = 0
    spread_paid: float = 0.0
    switches: list[tuple] = field(default_factory=list)   # (日期, 方向, 克数, 成交价)


def run_alloc(bars: list[Bar], target: list[float], cfg: dict, name: str,
              min_change: float = 0.2, cash_rate: float = 0.0) -> AllocResult:
    """按目标仓位持有黄金。

    min_change：目标仓位与当前仓位相差不到这个比例就不调仓（避免为小调整付点差）。
                目标仓位为 0 或从 0 变为非 0 时总是执行。
    cash_rate：空仓资金的年化收益（例如活期/货币基金），默认 0。
    """
    base_spread = float(cfg["broker"]["spread"])
    unit = int(cfg["account"]["min_unit_grams"])
    cash = float(cfg["account"]["capital"])
    grams = 0
    res = AllocResult(name, bars, cash, [], [])
    daily_cash = (1 + cash_rate) ** (1 / TRADING_DAYS) - 1

    for i, b in enumerate(bars):
        spread = base_spread * cost_scale(cfg, b.open)
        if i > 0:
            cash *= 1 + daily_cash
            want = target[i - 1]
            equity_open = cash + grams * (b.open - spread / 2)
            cur = grams * b.open / equity_open if equity_open > 0 else 0.0
            if (want == 0 and grams > 0) or (want > 0 and grams == 0) or abs(want - cur) >= min_change:
                goal = math.floor(want * equity_open / (b.open + spread / 2) / unit) * unit
                delta = goal - grams
                if delta > 0:
                    cash -= delta * (b.open + spread / 2)
                elif delta < 0:
                    cash += -delta * (b.open - spread / 2)
                if delta:
                    res.trades += 1
                    res.spread_paid += abs(delta) * spread / 2
                    res.switches.append((b.date, "买入" if delta > 0 else "卖出", abs(delta), b.open))
                    grams = goal
        eq = cash + grams * (b.close - spread / 2)
        res.equity.append(eq)
        res.weights.append(grams * b.close / eq if eq > 0 else 0.0)
    return res


def alloc_stats(res: AllocResult) -> dict:
    eq = res.equity
    years = (res.bars[-1].date - res.bars[0].date).days / 365.25
    peak, mdd, dd_start, worst = eq[0], 0.0, 0, (None, None)
    peak_i = 0
    for i, v in enumerate(eq):
        if v > peak:
            peak, peak_i = v, i
        dd = 1 - v / peak
        if dd > mdd:
            mdd, worst = dd, (res.bars[peak_i].date, res.bars[i].date)
    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq))]
    m = sum(rets) / len(rets)
    vol = math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1)) * math.sqrt(TRADING_DAYS)
    cagr = (eq[-1] / res.capital) ** (1 / years) - 1
    return {
        "final": eq[-1],
        "return": eq[-1] / res.capital - 1,
        "cagr": cagr,
        "vol": vol,
        "max_dd": mdd,
        "dd_window": worst,
        "calmar": cagr / mdd if mdd else float("inf"),
        "trades": res.trades,
        "trades_per_year": res.trades / years,
        "exposure": sum(res.weights) / len(res.weights),
        "spread_paid": res.spread_paid,
    }


# ---- 规则清单（预先定好，避免事后挑参数）----

def rule_book(bars: list[Bar]) -> dict[str, dict]:
    """返回 {规则名: {"weights": [...], "family": 规则族, "label": 中文说明}}。"""
    rules = {"buy_hold": {"weights": [1.0] * len(bars), "family": "参照", "label": "一直满仓持有"}}
    for n in (100, 150, 200, 250):
        rules[f"sma{n}"] = {"weights": sma_filter(bars, n), "family": "均线过滤", "label": f"价格在 {n} 日均线上方持有"}
    for f, s in ((20, 100), (50, 150), (50, 200), (100, 250)):
        rules[f"cross{f}_{s}"] = {"weights": sma_cross(bars, f, s), "family": "均线交叉", "label": f"{f} 日线在 {s} 日线上方持有"}
    for e, x in ((50, 25), (100, 50), (150, 75), (200, 100)):
        rules[f"donchian{e}_{x}"] = {"weights": donchian(bars, e, x), "family": "通道突破", "label": f"创 {e} 日新高买入，跌破 {x} 日低点卖出"}
    for lb in (126, 189, 252):
        rules[f"mom{lb}"] = {"weights": momentum(bars, lb), "family": "时间序列动量", "label": f"过去 {lb} 日上涨则持有（每月调整）"}
    base = sma_filter(bars, 200)
    for t in (0.08, 0.12, 0.16):
        rules[f"sma200_vt{int(t * 100)}"] = {"weights": vol_target(bars, base, t), "family": "均线 + 波动率控仓",
                                             "label": f"200 日均线过滤，按年化波动 {t:.0%} 控制仓位"}
    return rules


# ---- 研究：全规则对比、前后半段稳定性、按回撤上限缩放仓位 ----

def _slice(bars, w, pred):
    idx = [i for i, b in enumerate(bars) if pred(b.date)]
    return bars[idx[0]:idx[-1] + 1], w[idx[0]:idx[-1] + 1]


def scale_for_drawdown(bars, w, cfg, limit: float) -> tuple[float, dict]:
    """二分查找最大的仓位系数 k，使 k×目标仓位 的历史最大回撤不超过 limit。"""
    lo, hi = 0.0, 1.0
    for _ in range(14):
        mid = (lo + hi) / 2
        if alloc_stats(run_alloc(bars, [x * mid for x in w], cfg, "s"))["max_dd"] > limit:
            hi = mid
        else:
            lo = mid
    return lo, alloc_stats(run_alloc(bars, [x * lo for x in w], cfg, "s"))


def analyze(full: list[Bar], cfg: dict, warmup: int = 250, split: str = "2018-07-01",
            dd_limits=(0.05, 0.10)) -> dict:
    from .research import period_returns
    rules = rule_book(full)
    bars = full[warmup:]                     # 所有规则都等指标就绪后再开始比较
    periods = cfg.get("report", {}).get("periods", [])
    out = {"bars": bars, "split": split, "dd_limits": dd_limits, "rules": {}}
    for key, r in rules.items():
        w = r["weights"][warmup:]
        res = run_alloc(bars, w, cfg, key)
        b1, w1 = _slice(bars, w, lambda d: d.isoformat() < split)
        b2, w2 = _slice(bars, w, lambda d: d.isoformat() >= split)
        out["rules"][key] = {
            **r, "result": res, "stats": alloc_stats(res),
            "half": [alloc_stats(run_alloc(b1, w1, cfg, key)), alloc_stats(run_alloc(b2, w2, cfg, key))],
            "budget": [scale_for_drawdown(bars, w, cfg, lim) for lim in dd_limits],
            "period": period_returns(res, periods),
        }
    return out
