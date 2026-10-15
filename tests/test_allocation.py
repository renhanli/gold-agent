import datetime as dt
import unittest

from gold_agent import allocation as al
from gold_agent.data import Bar

CFG = {"account": {"capital": 100000, "min_unit_grams": 1}, "broker": {"spread": 5.0}}


def bars(closes):
    d0 = dt.date(2026, 1, 5)
    return [Bar(d0 + dt.timedelta(days=i), c, c, c, c) for i, c in enumerate(closes)]


class RunAllocTest(unittest.TestCase):
    def test_buys_next_open_and_pays_half_spread_each_way(self):
        b = bars([1000, 1000, 1100, 1100])
        r = al.run_alloc(b, [1, 1, 0, 0], CFG, "t")
        # 第 1 天开盘买入：100000 / 1002.5 = 99 克；第 3 天开盘按 1100 - 2.5 卖出
        self.assertEqual(r.trades, 2)
        self.assertEqual(r.switches[0][2], 99)
        cash_after_buy = 100000 - 99 * 1002.5
        self.assertAlmostEqual(r.equity[-1], cash_after_buy + 99 * 1097.5)
        self.assertAlmostEqual(r.spread_paid, 99 * 5.0)

    def test_small_weight_changes_are_ignored(self):
        b = bars([1000] * 5)
        r = al.run_alloc(b, [1, 0.9, 0.95, 0.9, 0.9], CFG, "t", min_change=0.2)
        self.assertEqual(r.trades, 1)            # 只有第一次建仓

    def test_cash_rate_accrues(self):
        b = bars([1000] * 253)
        r = al.run_alloc(b, [0] * 253, CFG, "t", cash_rate=0.02)
        self.assertAlmostEqual(r.equity[-1] / 100000, 1.02, places=3)


class RulesTest(unittest.TestCase):
    def test_sma_filter_hysteresis(self):
        closes = [100] * 5 + [110, 102, 99.5, 98]       # 第 6 天：102 vs 均线 102.4，在 ±1% 带内
        w = al.sma_filter(bars(closes), n=5, band=0.01)
        self.assertEqual(w[5], 1.0)              # 明显高于均线：持有
        self.assertEqual(w[6], 1.0)              # 落在 ±1% 带内：维持
        self.assertEqual(w[-1], 0.0)             # 跌破均线 1% 以下：空仓

    def test_momentum_only_changes_at_month_end(self):
        d0 = dt.date(2026, 1, 1)
        b = [Bar(d0 + dt.timedelta(days=i), c, c, c, c) for i, c in enumerate(range(100, 160))]
        w = al.momentum(b, lookback=5, monthly=True)
        jan_end = max(i for i, x in enumerate(b) if x.date.month == 1)
        self.assertEqual(set(w[:jan_end]), {0.0})
        self.assertEqual(w[jan_end], 1.0)


if __name__ == "__main__":
    unittest.main()
