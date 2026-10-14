"""回测引擎（日线、只做多）。

成交假设（偏保守）：
- 第 i 天收盘出信号，第 i+1 天开盘按 买入价 = 中间价 + 点差/2 成交
- 卖出按 卖出价 = 中间价 - 点差/2
- 开盘价已经跌破止损（跳空）→ 按开盘价止损，而不是止损价
- 同一天既碰到止损又碰到止盈 → 按止损算
- 移动止损在每天收盘后更新，从下一天开始生效
- 持有满 max_hold_days 个交易日仍未离场 → 当天收盘卖出
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

from .data import Bar
from .strategy import Strategy


@dataclass
class Trade:
    entry_date: dt.date
    exit_date: dt.date
    grams: int
    entry_mid: float
    exit_mid: float
    spread: float
    reason: str
    exit_reason: str
    hold_days: int

    @property
    def pnl_per_gram(self) -> float:
        """扣除点差后的每克盈亏。"""
        return self.exit_mid - self.entry_mid - self.spread

    @property
    def pnl(self) -> float:
        return self.pnl_per_gram * self.grams


@dataclass
class Result:
    name: str
    bars: list[Bar]
    capital: float
    equity: list[float]
    trades: list[Trade] = field(default_factory=list)
    halts: list[dt.date] = field(default_factory=list)


def cost_scale(cfg: dict, price: float) -> float:
    """按金价缩放固定金额成本（点差、最小止损）的系数；不缩放时为 1。"""
    broker = cfg["broker"]
    if broker.get("scale_with_price") and broker.get("ref_price"):
        return price / float(broker["ref_price"])
    return 1.0


@dataclass
class _Position:
    grams: int
    spread: float
    entry_mid: float
    stop: float
    tp: float | None
    high: float
    entry_idx: int
    reason: str


def run(strategy: Strategy, cfg: dict, name: str | None = None) -> Result:
    bars = strategy.bars
    acct, dd_cfg, broker = cfg["account"], cfg["drawdown"], cfg["broker"]
    base_spread = float(broker["spread"])
    unit = int(acct["min_unit_grams"])

    cash = float(acct["capital"])
    res = Result(name or strategy.name, bars, cash, [])
    pos: _Position | None = None
    pending = None
    hwm = cash               # 历史最高权益（用来判断是否减半风险）
    halt_peak = cash         # 判断是否暂停的基准（暂停结束后重置）
    halted_until = -1

    def close_position(i: int, mid: float, why: str) -> None:
        nonlocal cash, pos
        cash += pos.grams * (mid - pos.spread / 2)
        res.trades.append(Trade(bars[pos.entry_idx].date, bars[i].date, pos.grams, pos.entry_mid, mid,
                                pos.spread, pos.reason, why, i - pos.entry_idx + 1))
        pos = None

    for i, b in enumerate(bars):
        # 1) 开盘执行昨天的信号
        if pending is not None and pos is None:
            equity = cash
            risk_mult = 0.5 if equity < hwm * (1 - float(dd_cfg["reduce_at"])) or halted_until >= 0 else 1.0
            budget = equity * float(acct["risk_per_trade"]) * risk_mult
            spread = base_spread * cost_scale(cfg, b.open)
            loss_per_gram = pending.stop_dist + spread
            ask = b.open + spread / 2
            grams = math.floor(budget / loss_per_gram / unit) * unit
            grams = min(grams, math.floor(equity * float(acct["max_position_ratio"]) / ask / unit) * unit)
            if grams >= unit:
                cash -= grams * ask
                pos = _Position(grams, spread, b.open, b.open - pending.stop_dist,
                                b.open + pending.tp_dist if pending.tp_dist else None,
                                b.open, i, pending.reason)
        pending = None

        # 2) 盘中检查止损 / 止盈（入场当天也检查，开盘跳空只对之前的持仓有意义）
        if pos is not None:
            gap_ok = pos.entry_idx < i
            trailing = pos.stop >= pos.entry_mid
            if gap_ok and b.open <= pos.stop:
                close_position(i, b.open, "跳空移动止盈" if trailing else "跳空止损")
            elif b.low <= pos.stop:
                close_position(i, pos.stop, "移动止盈" if trailing else "止损")
            elif pos.tp is not None and gap_ok and b.open >= pos.tp:
                close_position(i, b.open, "止盈")
            elif pos.tp is not None and b.high >= pos.tp:
                close_position(i, pos.tp, "止盈")
            elif i - pos.entry_idx + 1 >= strategy.max_hold_days:
                close_position(i, b.close, "到期")

        # 3) 收盘后：更新移动止损
        if pos is not None:
            pos.high = max(pos.high, b.high)
            td = strategy.trail_dist(i)
            if td is not None:
                pos.stop = max(pos.stop, pos.high - td)

        # 4) 收盘权益 & 回撤风控
        equity = cash + (pos.grams * (b.close - pos.spread / 2) if pos else 0.0)
        res.equity.append(equity)
        hwm = max(hwm, equity)
        halt_peak = max(halt_peak, equity)
        if halted_until >= 0 and i >= halted_until:
            halted_until = -1
            halt_peak = equity
        if halted_until < 0 and equity <= halt_peak * (1 - float(dd_cfg["halt_at"])):
            halted_until = i + int(dd_cfg["halt_days"])
            res.halts.append(b.date)

        # 5) 收盘后：空仓且未暂停时检查信号
        if pos is None and halted_until < 0 and i < len(bars) - 1:
            pending = strategy.signal(i)

    if pos is not None:
        close_position(len(bars) - 1, bars[-1].close, "回测结束平仓")
        res.equity[-1] = cash
    return res


def buy_and_hold(bars: list[Bar], cfg: dict) -> Result:
    """对照组：第一天满仓买入一直拿着。"""
    spread = float(cfg["broker"]["spread"]) * cost_scale(cfg, bars[0].open)
    cap = float(cfg["account"]["capital"])
    grams = math.floor(cap / (bars[0].open + spread / 2))
    cash = cap - grams * (bars[0].open + spread / 2)
    eq = [cash + grams * (b.close - spread / 2) for b in bars]
    t = Trade(bars[0].date, bars[-1].date, grams, bars[0].open, bars[-1].close, spread,
              "第一天买入", "最后一天卖出", len(bars))
    return Result("buy_hold", bars, cap, eq, [t])


# ---- 统计 ----

def stats(res: Result) -> dict:
    eq, trades = res.equity, res.trades
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = max(mdd, 1 - v / peak)
    years = max((res.bars[-1].date - res.bars[0].date).days / 365.25, 1e-9)
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = -sum(t.pnl for t in losses)
    held = sum(t.hold_days for t in trades)
    return {
        "final": eq[-1],
        "return": eq[-1] / res.capital - 1,
        "cagr": (eq[-1] / res.capital) ** (1 / years) - 1,
        "max_dd": mdd,
        "trades": len(trades),
        "trades_per_year": len(trades) / years,
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "avg_win_g": sum(t.pnl_per_gram for t in wins) / len(wins) if wins else 0.0,
        "avg_loss_g": sum(t.pnl_per_gram for t in losses) / len(losses) if losses else 0.0,
        "avg_pnl_g": sum(t.pnl_per_gram for t in trades) / len(trades) if trades else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss else float("inf"),
        "avg_hold": held / len(trades) if trades else 0.0,
        "exposure": held / len(res.bars),
        "spread_cost": sum(t.spread * t.grams for t in trades),
        "halts": len(res.halts),
    }


def yearly_returns(res: Result) -> dict[int, float]:
    out, start = {}, res.capital
    for i, b in enumerate(res.bars):
        last = i == len(res.bars) - 1 or res.bars[i + 1].date.year != b.date.year
        if last:
            out[b.date.year] = res.equity[i] / start - 1
            start = res.equity[i]
    return out
