"""The MT5 EA gets a plain-text answer it can show without a JSON parser."""
import unittest
from datetime import datetime, timezone

from guardian import mt5

NOW = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)
ACC = {"equity": 10000, "risk_pct": 1, "open_trades": 3, "open_risk": 200, "open_no_stop": 1}


class Mt5Test(unittest.TestCase):
    def test_nas100_no_stop(self):
        body = {"trade": {"sym": "NAS100.cash", "side": "buy", "lots": 0.15, "stop": 0, "per_lot": None},
                "account": ACC}
        ev = [{"ts": NOW.timestamp() + 20 * 60, "currency": "USD", "impact": "High", "title": "ISM Services PMI"}]
        lines = mt5.answer(body, ev, now=NOW).split("\n")
        self.assertEqual(lines[0], "NO")
        self.assertTrue(lines[1].startswith("⛔ GUARDIAN NO. Sit this out. NAS100.cash BUY 0.15 lots No stop loss:"))
        self.assertLessEqual(len(lines[1]), 255)
        self.assertEqual(len(lines), 2 + 3)            # no stop, naked open trade, news
        self.assertIn("ISM Services PMI is out in 20 min", lines[-1])

    def test_on_plan_is_ok(self):
        body = {"trade": {"sym": "XAUUSD", "side": "sell", "lots": 0.1, "stop": 10, "per_lot": 1000},
                "account": {"equity": 10000, "risk_pct": 1}}
        self.assertEqual(mt5.answer(body, [], now=NOW).split("\n")[0], "OK")

    def test_challenge_passed_through(self):
        acc = dict(ACC, open_no_stop=0, challenge={"on": True, "start": 10000, "daily_pct": 5, "max_pct": 10,
                                                    "today_pl": -450})
        body = {"trade": {"sym": "XAUUSD", "lots": 0.1, "stop": 10, "per_lot": 1000}, "account": acc}
        self.assertIn("could fail your challenge", mt5.answer(body, [], now=NOW))

    def test_bad_body(self):
        self.assertTrue(mt5.answer({}, []).startswith("ERROR"))
        self.assertTrue(mt5.answer({"trade": {"sym": "X", "lots": 1, "per_lot": 1}, "account": {}}, []).startswith("ERROR"))


if __name__ == "__main__":
    unittest.main()
