"""命令行入口。

    python -m gold_agent backtest            # 跑全部策略，生成 reports/backtest.html
    python -m gold_agent trend               # 方向 A：趋势择时持有，生成 reports/trend.html
    python -m gold_agent signal              # 用最新数据看各策略今天有没有买入信号
    python -m gold_agent update-data         # 从 Twelve Data 下载 2010 年起日线 + 2020 年起小时线
    python -m gold_agent backtest --source session   # 用招行交易时段日线回测
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import tomllib

from . import allocation, report, research, trend_report
from .backtest import cost_scale
from .data import load_bars, update_data
from .strategy import STRATEGIES

NAMES = report.NAMES


def load_config(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def bars_from_config(cfg: dict):
    d = cfg["data"]
    path = d["session_csv"] if d.get("source") == "session" else d["gold_csv"]
    return load_bars(path, d["fx_csv"], cfg["broker"]["premium"], research.ref_price(cfg))


def cmd_backtest(cfg: dict, args) -> None:
    if args.source:
        cfg["data"]["source"] = args.source
    if args.start:
        cfg["data"]["start"] = args.start
    bars = [b for b in bars_from_config(cfg) if b.date.isoformat() >= cfg["data"].get("start", "")]
    out = research.run_all(bars, cfg)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(report.build(out, cfg, dt.datetime.now()))
    print(f"数据 {bars[0].date} ~ {bars[-1].date}，{len(bars)} 个交易日\n")
    print(f"{'策略':<12}{'总收益':>8}{'最大回撤':>9}{'交易数':>7}{'胜率':>7}{'每克净盈亏':>10}{'跑赢随机':>9}")
    for name, d in out["strategies"].items():
        s = d["stats"]
        print(f"{NAMES[name]:<10}{s['return']:>+10.1%}{s['max_dd']:>9.1%}{s['trades']:>8}"
              f"{s['win_rate']:>8.0%}{s['avg_pnl_g']:>+11.1f}{d['random']['beat']:>10.0%}")
    s = out["buy_hold"]["stats"]
    print(f"{NAMES['buy_hold']:<10}{s['return']:>+10.1%}{s['max_dd']:>9.1%}")
    print(f"\n报告已生成：{args.out}")


def cmd_trend(cfg: dict, args) -> None:
    out = allocation.analyze(bars_from_config(cfg), cfg)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(trend_report.build(out, cfg, dt.datetime.now()))
    bars = out["bars"]
    print(f"数据 {bars[0].date} ~ {bars[-1].date}，{len(bars)} 个交易日\n")
    lims = out["dd_limits"]
    print(f"{'规则':<14}{'年化':>7}{'最大回撤':>8}{'交易/年':>7}" + "".join(f"{'回撤≤' + format(x, '.0%') + '年化':>12}" for x in lims))
    for key, r in out["rules"].items():
        s = r["stats"]
        print(f"{key:<16}{s['cagr']:>+7.1%}{s['max_dd']:>9.1%}{s['trades_per_year']:>8.1f}"
              + "".join(f"{st['cagr']:>+13.2%}" for _, st in r["budget"]))
    print(f"\n报告已生成：{args.out}")


def cmd_signal(cfg: dict, args) -> None:
    bars = bars_from_config(cfg)
    last = bars[-1]
    half = cfg["broker"]["spread"] * cost_scale(cfg, last.close) / 2
    print(f"{last.date} 收盘中间价 {last.close:.2f}（买入价约 {last.close + half:.2f}，卖出价约 {last.close - half:.2f}）")
    for name in STRATEGIES:
        sig = research.make(name, bars, cfg["strategy"][name], cfg).signal(len(bars) - 1)
        if sig is None:
            print(f"  {NAMES[name]}：无信号")
        else:
            entry = last.close
            tp = f"，止盈 {entry + sig.tp_dist:.1f}" if sig.tp_dist else "，移动止盈"
            print(f"  {NAMES[name]}：买入信号（{sig.reason}）参考价 {entry:.1f}，止损 {entry - sig.stop_dist:.1f}{tp}")


def cmd_update(cfg: dict, args) -> None:
    update_data(cfg["data"], args.start, args.end or dt.date.today().isoformat(),
                None if args.no_hourly else args.hourly_start, pause=args.pause)
    print("数据已更新")


def main() -> None:
    ap = argparse.ArgumentParser(prog="gold_agent", description="纸黄金短线交易助手")
    ap.add_argument("--config", default="config.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest", help="回测全部策略并生成 HTML 报告")
    b.add_argument("--out", default="reports/backtest.html")
    b.add_argument("--source", choices=["daily", "session"], help="覆盖 config 里的 data.source")
    b.add_argument("--start", help="只用这一天之后的数据，例如 2010-01-01")
    t = sub.add_parser("trend", help="方向 A：趋势择时持有的回测与报告")
    t.add_argument("--out", default="reports/trend.html")
    sub.add_parser("signal", help="查看最新一天的信号")
    u = sub.add_parser("update-data", help="从 Twelve Data 更新数据")
    u.add_argument("--start", default="2010-01-01", help="日线起始日")
    u.add_argument("--end")
    u.add_argument("--hourly-start", default="2020-01-24", help="小时线起始日（用于合成招行时段日线）")
    u.add_argument("--no-hourly", action="store_true", help="不下载小时线")
    u.add_argument("--pause", type=float, default=8.0, help="两次请求之间等待秒数（免费套餐每分钟 8 次）")
    args = ap.parse_args()
    cfg = load_config(args.config)
    {"backtest": cmd_backtest, "trend": cmd_trend, "signal": cmd_signal, "update-data": cmd_update}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
