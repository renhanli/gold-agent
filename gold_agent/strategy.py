"""交易规则。每个策略在第 i 天收盘后判断是否发出买入信号，第 i+1 天开盘成交。

策略只负责"什么时候买、止损止盈放多远"；仓位、点差、风控由回测引擎统一处理，
这样回测和以后的实盘提醒用的是同一套逻辑。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from . import indicators as ind
from .data import Bar


@dataclass(frozen=True)
class Signal:
    reason: str
    stop_dist: float            # 入场价到止损的距离（元/克，中间价）
    tp_dist: float | None       # 入场价到止盈的距离；None = 不设固定止盈


class Strategy:
    name = "base"

    def __init__(self, bars: list[Bar], params: dict, ref_price: float | None = None):
        self.bars = bars
        self.p = params
        self.ref_price = ref_price      # 设置后，min_stop 按 当前价/ref_price 缩放
        self.closes = [b.close for b in bars]
        self.atr = ind.atr(bars, int(params.get("atr_period", 14)))
        self.max_hold_days = int(params.get("max_hold_days", 15))

    def signal(self, i: int) -> Signal | None:
        raise NotImplementedError

    def trail_dist(self, i: int) -> float | None:
        """第 i 天收盘后的移动止损距离（从持仓期间最高价回落多少离场）。"""
        k = float(self.p.get("trail_atr", 0) or 0)
        if k <= 0 or self.atr[i] is None:
            return None
        return k * self.atr[i]

    def _exits(self, i: int, reason: str) -> Signal | None:
        a = self.atr[i]
        if a is None:
            return None
        min_stop = float(self.p["min_stop"])
        if self.ref_price:
            min_stop *= self.closes[i] / self.ref_price
        stop = max(float(self.p["stop_atr"]) * a, min_stop)
        tp_r = float(self.p.get("tp_r", 0) or 0)
        return Signal(reason, stop, tp_r * stop if tp_r > 0 else None)


class Pullback(Strategy):
    """上升趋势（收盘 > 50 日线且 20 日线 > 50 日线）中，前一天回踩到 20 日线附近，
    当天收阳并重新站上 20 日线，且 RSI 不过热。"""
    name = "pullback"

    def __init__(self, bars, params, ref_price=None):
        super().__init__(bars, params, ref_price)
        self.fast = ind.sma(self.closes, int(params["sma_fast"]))
        self.slow = ind.sma(self.closes, int(params["sma_slow"]))
        self.rsi = ind.rsi(self.closes, int(params["rsi_period"]))

    def signal(self, i):
        if i < 1 or None in (self.fast[i], self.slow[i], self.rsi[i], self.fast[i - 1]):
            return None
        b, prev = self.bars[i], self.bars[i - 1]
        uptrend = b.close > self.slow[i] and self.fast[i] > self.slow[i]
        touched = prev.low <= self.fast[i - 1] * 1.003
        recovered = b.close > b.open and b.close > self.fast[i]
        if uptrend and touched and recovered and self.rsi[i] <= float(self.p["rsi_max"]):
            return self._exits(i, f"回踩20日线企稳，RSI {self.rsi[i]:.0f}")
        return None


class Breakout(Strategy):
    """收盘价突破前 N 日最高价，且在 50 日线上方。"""
    name = "breakout"

    def __init__(self, bars, params, ref_price=None):
        super().__init__(bars, params, ref_price)
        self.hh = ind.highest([b.high for b in bars], int(params["channel"]))
        self.slow = ind.sma(self.closes, int(params["sma_slow"]))

    def signal(self, i):
        if self.hh[i] is None or self.slow[i] is None:
            return None
        b = self.bars[i]
        if b.close > self.hh[i] and b.close > self.slow[i]:
            return self._exits(i, f"突破{self.p['channel']}日高点 {self.hh[i]:.1f}")
        return None


class RsiRebound(Strategy):
    """收盘在 100 日线上方，RSI 由 rsi_low 以下回升到其上方。"""
    name = "rsi_rebound"

    def __init__(self, bars, params, ref_price=None):
        super().__init__(bars, params, ref_price)
        self.trend = ind.sma(self.closes, int(params["sma_trend"]))
        self.rsi = ind.rsi(self.closes, int(params["rsi_period"]))

    def signal(self, i):
        if i < 1 or None in (self.trend[i], self.rsi[i], self.rsi[i - 1]):
            return None
        lo = float(self.p["rsi_low"])
        if self.closes[i] > self.trend[i] and self.rsi[i - 1] < lo <= self.rsi[i]:
            return self._exits(i, f"RSI 从 {self.rsi[i - 1]:.0f} 回升到 {self.rsi[i]:.0f}")
        return None


class RandomEntry(Strategy):
    """对照组：随机日子入场，止损止盈规则和被比较的策略完全相同。
    用来回答"这个策略的入场信号到底比瞎买好多少"。"""
    name = "random"

    def __init__(self, bars, params, prob: float, seed: int, ref_price: float | None = None):
        super().__init__(bars, params, ref_price)
        self.prob = prob
        self.rng = random.Random(seed)

    def signal(self, i):
        if self.rng.random() < self.prob:
            return self._exits(i, "随机入场")
        return None


STRATEGIES = {cls.name: cls for cls in (Pullback, Breakout, RsiRebound)}
