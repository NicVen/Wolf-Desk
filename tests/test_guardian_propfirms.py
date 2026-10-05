import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from guardian import live, mt5, propfirms, rules  # noqa: E402

SNAP = {"login": "7200717", "balance": 101000, "equity": 100400, "day_start": 100800, "day_start_bal": 101000,
        "risk_pct": 1, "positions": [{"sym": "XAUUSD.r", "side": "BUY", "lots": 1, "open": 4150, "sl": 4140,
                                      "profit": -600, "risk": 1000}],
        "symbols": [{"s": "XAUUSD.r", "bid": 4144, "v": 100, "digits": 2}]}


class Presets(unittest.TestCase):
    def test_every_preset_is_complete(self):
        for pid in propfirms.PRESETS:
            p = propfirms.get(pid)
            self.assertGreater(p["max_pct"], 0, pid)
            self.assertIn(p["max_type"], ("static", "trailing", "trailing_lock", "eod_trailing"), pid)
            if p["daily_pct"]:
                self.assertIn(p["daily_basis"], ("balance", "equity", "equity_or_balance"), pid)
            self.assertTrue(p["sizes"] and p["source"].startswith("https://"), pid)
            propfirms.summary(p, p["sizes"][0])

    def test_floors(self):
        ftmo = propfirms.get("ftmo-2")                        # 5% daily from balance, 10% static
        self.assertEqual(propfirms.floors(ftmo, 100000, {"day_bal": 102000, "day_eq": 101000}), (97000, 90000))
        fx1 = propfirms.get("fxify-1")                        # 6% trailing, locks at the start size
        self.assertEqual(propfirms.floors(fx1, 100000, {"day_bal": 100000, "peak_eq": 103000})[1], 97000)
        self.assertEqual(propfirms.floors(fx1, 100000, {"day_bal": 100000, "peak_eq": 109000})[1], 100000)
        bg = propfirms.get("bg-2")                            # higher of balance or equity
        self.assertEqual(propfirms.floors(bg, 100000, {"day_bal": 100000, "day_eq": 101000})[0], 97000)
        self.assertIsNone(propfirms.floors(propfirms.get("fxify-if"), 100000, {})[0])
        self.assertIn("Daily loss 3% ($3,000)", propfirms.summary(fx1, 100000))


class ChosenInApp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        live.save("K", SNAP, d=self.d.name, now=1000)

    def tearDown(self):
        self.d.cleanup()

    def test_firm_choice_drives_phone_and_pc(self):
        live.set_challenge("K", {"preset": "fxify-1", "size": 100000, "risk_pct": 0.5}, d=self.d.name, now=1000)
        s = live.load("K", d=self.d.name, now=1000)
        self.assertEqual(s["firm"]["firm"], "FXIFY")
        self.assertEqual(s["risk_pct"], 0.5)
        self.assertEqual(s["firm"]["daily_floor"], 98000)      # 101,000 day-start balance - 3%
        self.assertEqual(s["firm"]["max_floor"], 94400)        # trails from today's 100,400 high - 6%
        self.assertEqual(s["firm"]["daily_left"], 2400)
        r = rules.check(live.trade(s, "XAUUSD.r", 2, 4134), live.account(s))   # $2,000 more at stake
        self.assertIn(("challenge", "NO"), [(c["kind"], c["level"]) for c in r["checks"]])
        # the PC's EA asks with its own inputs; the app's choice wins
        ch, risk, _ = live.rules_for("K", equity=100400, d=self.d.name, now=1000)
        out = mt5.answer({"trade": {"sym": "XAUUSD.r", "lots": 2, "stop": 10, "per_lot": 1000},
                          "account": {"equity": 100400, "risk_pct": risk, "open_trades": 1, "open_risk": 1000,
                                      "challenge": ch}}, now=None)
        self.assertTrue(out.startswith("NO"))

    def test_trailing_high_follows_the_account(self):
        live.set_challenge("K", {"preset": "fxify-1", "size": 100000}, d=self.d.name, now=1000)
        live.save("K", dict(SNAP, equity=104000, balance=104000), d=self.d.name, now=1010)
        live.save("K", dict(SNAP, equity=102000, balance=102000), d=self.d.name, now=1020)
        s = live.load("K", d=self.d.name, now=1020)
        self.assertEqual(s["firm"]["max_floor"], 98000)        # 104,000 high - 6%

    def test_custom_and_off(self):
        live.set_challenge("K", {"preset": "custom", "size": 50000, "daily_pct": 4, "max_pct": 8}, d=self.d.name)
        self.assertEqual(live.load("K", d=self.d.name)["firm"]["max_floor"], 46000)
        live.set_challenge("K", {"preset": ""}, d=self.d.name)
        self.assertNotIn("firm", live.load("K", d=self.d.name))
        with self.assertRaises(ValueError):
            live.set_challenge("K", {"preset": "nope", "size": 100000}, d=self.d.name)


if __name__ == "__main__":
    unittest.main()
