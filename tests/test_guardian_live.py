import os
"""The phone's Guardian screen runs on the EA's live account snapshot."""
import tempfile
import unittest

from guardian import live, rules

SNAP = {
    "key": "K", "login": "7200717", "server": "FXIFY-Live", "currency": "USD",
    "balance": 100000, "equity": 99550, "day_start": 100000, "risk_pct": 0.5,
    "challenge": {"on": True, "start": 100000, "daily_pct": 4, "max_pct": 10},
    "positions": [
        {"sym": "XAUUSD", "side": "BUY", "lots": 1, "open": 4000, "sl": 3990, "profit": -120, "risk": 1000},
        {"sym": "NAS100", "side": "SELL", "lots": 0.5, "open": 25000, "sl": 0, "profit": 40, "risk": None},
    ],
    "symbols": [{"s": "NAS100", "bid": 25010, "v": 1, "digits": 2},
                {"s": "XAUUSD", "bid": 4002.5, "v": 100, "digits": 2},
                {"s": "JUNK", "bid": 1, "v": 0}],
}


class LiveTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.d.cleanup()

    def test_save_load_and_totals(self):
        live.save("K", SNAP, d=self.d.name, now=1000)
        s = live.load("K", d=self.d.name, now=1030)
        self.assertTrue(s["live"])
        self.assertEqual(s["age"], 30)
        self.assertEqual(s["open_risk"], 1000)
        self.assertEqual(s["open_no_stop"], 1)
        self.assertEqual(s["today_pl"], -450)
        self.assertEqual([x["s"] for x in s["symbols"]], ["NAS100", "XAUUSD"])   # junk dropped
        self.assertFalse(live.load("K", d=self.d.name, now=1000 + live.STALE + 1)["live"])
        self.assertIsNone(live.load("other", d=self.d.name))

    def test_purge_deletes_everything_for_the_key(self):
        live.save("K", SNAP, d=self.d.name, now=1000)
        live.claim_account("K", "7200717", d=self.d.name)
        self.assertTrue(os.listdir(self.d.name))
        live.purge("k ", d=self.d.name)
        self.assertEqual(os.listdir(self.d.name), [])
        live.purge("K", d=self.d.name)                     # nothing left: no error

    def test_ask_from_live_account(self):
        live.save("K", SNAP, d=self.d.name, now=1000)
        s = live.load("K", d=self.d.name, now=1000)
        t = live.trade(s, "NAS100", 0.15, 24910)               # 100 points x $1 x 0.15 = $15
        self.assertAlmostEqual(t["per_lot"] * t["lots"], 15)
        r = rules.check(t, live.account(s))
        got = [(c["kind"], c["level"]) for c in r["checks"]]
        self.assertIn(("size", "OK"), got)                     # $15 of $99,550 at a 0.5% plan
        self.assertIn(("heat", "NO"), got)                     # the NAS100 sell has no stop
        self.assertIn(("challenge", "OK"), got)                # $3,550 left today, $1,015 at stake
        self.assertEqual(r["verdict"], "NO")
        self.assertIsNone(live.trade(s, "EURUSD", 1, 1.1))

    def test_bad_values_cleaned(self):
        snap = live.clean({"equity": "abc", "positions": ["x", {"sym": "A" * 99, "lots": "1"}], "symbols": None})
        self.assertEqual(snap["equity"], 0)
        self.assertEqual(len(snap["positions"]), 1)
        self.assertEqual(len(snap["positions"][0]["sym"]), 32)

    def test_same_key_any_case_or_spaces(self):
        # the key typed into MT5 and the one in the app must meet on one file
        live.save(" toolkit-9e11f913 ", SNAP, d=self.d.name, now=1000)
        self.assertIsNotNone(live.load("TOOLKIT-9E11F913", d=self.d.name, now=1000))

    def test_mt5_nan_and_inf_do_not_lose_the_snapshot(self):
        raw = ('{"key":"K","equity":1000,"positions":[{"sym":"X","sl":nan,"risk":-nan(ind)}],'
               '"symbols":[{"s":"A","bid":1,"v":inf},{"s":"B","bid":2,"v":3}]}')
        snap = live.clean(live.parse(raw))
        self.assertEqual(snap["equity"], 1000)
        self.assertIsNone(snap["positions"][0]["risk"])
        self.assertEqual([x["s"] for x in snap["symbols"]], ["B"])


if __name__ == "__main__":
    unittest.main()
