"""回测研究：多策略对比、随机入场对照、参数稳健性。"""

from __future__ import annotations

import copy
import itertools
import statistics as st

from . import backtest as bt
from .data import Bar
from .strategy import STRATEGIES, RandomEntry

# 每个策略要扫描的参数网格：看"换一组参数还赚不赚钱"，而不是挑最好的那组
GRIDS = {
    "pullback": {"stop_atr": [1.0, 1.5, 2.0], "tp_r": [1.0, 1.5, 2.0, 3.0]},
    "breakout": {"channel": [10, 20, 40], "trail_atr": [2.0, 3.0, 4.0], "stop_atr": [1.5, 2.0, 3.0]},
    "rsi_rebound": {"rsi_low": [40, 45, 50], "stop_atr": [1.0, 1.5, 2.0], "tp_r": [1.0, 1.5, 2.0]},
}

RANDOM_RUNS = 200


def ref_price(cfg: dict) -> float | None:
    b = cfg["broker"]
    return float(b["ref_price"]) if b.get("scale_with_price") and b.get("ref_price") else None


def make(name: str, bars: list[Bar], params: dict, cfg: dict):
    return STRATEGIES[name](bars, params, ref_price(cfg))


def period_returns(res: bt.Result, periods: list[dict]) -> list[float | None]:
    """每个阶段的收益（按资金曲线首尾计算）；数据不覆盖该阶段时为 None。"""
    out = []
    for p in periods:
        idx = [i for i, b in enumerate(res.bars) if p["start"] <= b.date.isoformat() <= p["end"]]
        if len(idx) < 20:
            out.append(None)
            continue
        i0 = idx[0] - 1 if idx[0] > 0 else None
        base = res.equity[i0] if i0 is not None else res.capital
        out.append(res.equity[idx[-1]] / base - 1)
    return out


def random_baseline(bars: list[Bar], cfg: dict, name: str, res: bt.Result) -> dict:
    """用相同的离场规则、相近的交易频率随机入场 200 次，看策略排在第几。"""
    s = bt.stats(res)
    free_days = max(1.0, len(bars) * (1 - s["exposure"]))
    prob = min(0.5, max(s["trades"], 1) / free_days)
    rets = []
    for seed in range(RANDOM_RUNS):
        r = bt.run(RandomEntry(bars, cfg["strategy"][name], prob, seed, ref_price(cfg)), cfg)
        rets.append(bt.stats(r)["return"])
    rets.sort()
    beat = sum(1 for x in rets if x < s["return"]) / len(rets)
    return {"mean": st.mean(rets), "median": st.median(rets),
            "p10": rets[len(rets) // 10], "p90": rets[len(rets) * 9 // 10], "beat": beat}


def param_grid(bars: list[Bar], cfg: dict, name: str) -> list[dict]:
    grid = GRIDS[name]
    keys = list(grid)
    rows = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        params = dict(cfg["strategy"][name], **dict(zip(keys, combo)))
        r = bt.run(make(name, bars, params, cfg), cfg)
        s = bt.stats(r)
        rows.append({"params": dict(zip(keys, combo)), **s})
    return rows


def run_all(bars: list[Bar], cfg: dict) -> dict:
    periods = cfg.get("report", {}).get("periods", [])
    out = {"strategies": {}, "buy_hold": None, "periods": periods}
    for name in STRATEGIES:
        res = bt.run(make(name, bars, cfg["strategy"][name], cfg), cfg)
        grid = param_grid(bars, cfg, name)
        rets = [g["return"] for g in grid]
        out["strategies"][name] = {
            "result": res,
            "stats": bt.stats(res),
            "yearly": bt.yearly_returns(res),
            "period": period_returns(res, periods),
            "random": random_baseline(bars, cfg, name, res),
            "grid": grid,
            "grid_summary": {
                "n": len(grid),
                "profitable": sum(1 for x in rets if x > 0) / len(grid),
                "median": st.median(rets),
                "best": max(rets),
                "worst": min(rets),
            },
            "description": cfg["strategy"][name].get("description", ""),
            "params": copy.deepcopy(cfg["strategy"][name]),
        }
    bh = bt.buy_and_hold(bars, cfg)
    out["buy_hold"] = {"result": bh, "stats": bt.stats(bh), "yearly": bt.yearly_returns(bh),
                       "period": period_returns(bh, periods)}
    return out
