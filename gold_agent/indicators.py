"""技术指标。输入为按时间升序的序列，数据不足的位置返回 None。"""

from __future__ import annotations

from .data import Bar


def sma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def rsi(closes: list[float], n: int = 14) -> list[float | None]:
    """Wilder RSI。"""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def atr(bars: list[Bar], n: int = 14) -> list[float | None]:
    """Wilder ATR（平均真实波幅）。"""
    out: list[float | None] = [None] * len(bars)
    trs = []
    for i, b in enumerate(bars):
        tr = b.high - b.low if i == 0 else max(
            b.high - b.low, abs(b.high - bars[i - 1].close), abs(b.low - bars[i - 1].close))
        trs.append(tr)
        if i == n - 1:
            out[i] = sum(trs) / n
        elif i >= n:
            out[i] = (out[i - 1] * (n - 1) + tr) / n
    return out


def highest(values: list[float], n: int) -> list[float | None]:
    """前 n 根（不含当根）的最高值。"""
    return [None if i < n else max(values[i - n:i]) for i in range(len(values))]
