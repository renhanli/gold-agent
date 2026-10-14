import unittest

from gold_agent import backtest as bt
from gold_agent.data import fetch_series, session_bars_from_hourly


def hour(ts, o, h, l, c):
    return {"datetime": ts, "open": o, "high": h, "low": l, "close": c}


class SessionBarsTest(unittest.TestCase):
    def test_keeps_only_cmb_session_hours(self):
        rows = [
            hour("2026-10-12 08:00:00", 1, 999, 0, 1),     # 开市前：不算
            hour("2026-10-12 09:00:00", 10, 12, 9, 11),    # 与 9:30 开市重叠：算
            hour("2026-10-12 15:00:00", 11, 20, 10, 18),
            hour("2026-10-12 23:00:00", 18, 19, 5, 7),     # 23:00-24:00：算
            hour("2026-10-13 00:00:00", 7, 999, 0, 7),     # 次日 0 点（休市）：不算
            hour("2026-10-17 10:00:00", 1, 2, 0, 1),       # 周六：不算
        ]
        bars = session_bars_from_hourly(rows)
        self.assertEqual(len(bars), 1)
        b = bars[0]
        self.assertEqual(b["date"], "2026-10-12")
        self.assertEqual((b["open"], b["high"], b["low"], b["close"]), (10, 20, 5, 7))


class FetchSeriesTest(unittest.TestCase):
    def test_pages_backwards_until_start(self):
        import gold_agent.data as data
        data.PAGE, old = 3, data.PAGE
        try:
            days = [f"2026-01-{d:02d}" for d in range(1, 8)]          # 7 天，每页 3 条
            calls = []

            def fake(params):
                calls.append(params["end_date"])
                vals = [d for d in days if params["start_date"] <= d <= params["end_date"][:10]]
                vals = sorted(vals, reverse=True)[:3]
                return {"status": "ok", "values": [{"datetime": d, "close": "1"} for d in vals]}

            out = fetch_series("XAU/USD", "1day", "2026-01-01", "2026-01-07", "k", pause=0, request=fake)
            self.assertEqual([r["datetime"] for r in out], days)
            self.assertGreater(len(calls), 2)
        finally:
            data.PAGE = old

    def test_raises_on_api_error(self):
        fake = lambda p: {"status": "error", "code": 401, "message": "bad key"}
        with self.assertRaises(RuntimeError):
            fetch_series("XAU/USD", "1day", "2026-01-01", "2026-01-07", "k", pause=0, request=fake)


class CostScaleTest(unittest.TestCase):
    def test_scale_with_price(self):
        cfg = {"broker": {"spread": 5.0, "scale_with_price": True, "ref_price": 900.0}}
        self.assertAlmostEqual(bt.cost_scale(cfg, 450.0), 0.5)
        cfg["broker"]["scale_with_price"] = False
        self.assertEqual(bt.cost_scale(cfg, 450.0), 1.0)


if __name__ == "__main__":
    unittest.main()
