import datetime as dt
import unittest

from gold_agent import backtest as bt
from gold_agent.data import Bar
from gold_agent.strategy import Signal, Strategy

CFG = {
    "account": {"capital": 100000, "risk_per_trade": 0.01, "max_position_ratio": 1.0, "min_unit_grams": 1},
    "drawdown": {"reduce_at": 0.03, "halt_at": 0.05, "halt_days": 20},
    "broker": {"spread": 5.0},
}


def bars(*ohlc):
    d0 = dt.date(2026, 1, 5)
    return [Bar(d0 + dt.timedelta(days=i), *x) for i, x in enumerate(ohlc)]


class OneShot(Strategy):
    """第 0 天收盘发出一次信号。"""

    def __init__(self, b, stop=20.0, tp=30.0, hold=15, trail=0.0):
        super().__init__(b, {"max_hold_days": hold, "trail_atr": trail, "atr_period": 1})
        self.sig = Signal("test", stop, tp)

    def signal(self, i):
        return self.sig if i == 0 else None


class BacktestTest(unittest.TestCase):
    def test_enters_next_open_and_pays_spread_on_take_profit(self):
        b = bars((900, 901, 899, 900), (910, 912, 905, 911), (911, 945, 910, 940))
        r = bt.run(OneShot(b), CFG)
        t = r.trades[0]
        self.assertEqual(t.entry_date, b[1].date)
        self.assertEqual(t.entry_mid, 910)
        self.assertEqual(t.exit_mid, 940)                 # 止盈价 = 910 + 30
        self.assertAlmostEqual(t.pnl_per_gram, 25)        # 30 - 5 点差
        self.assertEqual(t.grams, 40)                     # 1000 / (20 + 5)
        self.assertAlmostEqual(r.equity[-1], 100000 + 25 * 40)

    def test_gap_below_stop_exits_at_open(self):
        b = bars((900, 901, 899, 900), (900, 903, 895, 900), (870, 875, 860, 872))
        t = bt.run(OneShot(b), CFG).trades[0]
        self.assertEqual(t.exit_mid, 870)
        self.assertEqual(t.exit_reason, "跳空止损")
        self.assertAlmostEqual(t.pnl_per_gram, -35)

    def test_stop_wins_when_both_hit_same_day(self):
        b = bars((900, 901, 899, 900), (900, 903, 895, 900), (900, 940, 870, 900))
        t = bt.run(OneShot(b), CFG).trades[0]
        self.assertEqual(t.exit_reason, "止损")
        self.assertEqual(t.exit_mid, 880)

    def test_time_exit_at_close(self):
        b = bars((900, 901, 899, 900), (900, 903, 895, 900), (900, 905, 896, 902), (902, 906, 898, 904))
        t = bt.run(OneShot(b, hold=2), CFG).trades[0]
        self.assertEqual(t.exit_reason, "到期")
        self.assertEqual(t.exit_mid, 902)

    def test_trailing_stop_takes_effect_next_day(self):
        # ATR(1) = 当天真实波幅；trail_atr=1 时，移动止损 = 持仓最高价 - 当天真实波幅
        b = bars((900, 901, 899, 900), (900, 905, 899, 904), (904, 920, 903, 918), (918, 919, 902, 905))
        t = bt.run(OneShot(b, tp=None, trail=1.0), CFG).trades[0]
        self.assertEqual(t.exit_date, b[3].date)          # 第 2 天收盘才上移，第 2 天本身不触发
        self.assertEqual(t.exit_reason, "移动止盈")
        self.assertEqual(t.exit_mid, 920 - 17)            # 第 2 天 TR = max(920-903, 920-904, 904-903)

    def test_halts_after_drawdown(self):
        cfg = dict(CFG, account=dict(CFG["account"], risk_per_trade=0.06))
        # 止损 60 → 每克最多亏 65，买 92 克，止损亏 5,980 元 ≥ 5%
        b = bars((900, 901, 899, 900), (900, 903, 895, 900), (900, 900, 830, 840), (840, 841, 839, 840))
        r = bt.run(OneShot(b, stop=60.0), cfg)
        self.assertEqual(len(r.halts), 1)


if __name__ == "__main__":
    unittest.main()
