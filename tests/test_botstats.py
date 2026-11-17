"""HQ Bots tab: scoreboard maths from the bots' published records."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from licensing import botstats  # noqa: E402

NOW = datetime.datetime(2026, 11, 17, 8, 0, tzinfo=datetime.timezone.utc)

MARKOV = {
    "generated": "2026-11-17T07:31:59Z",
    "rules": {"stop_atr": 6, "target_r": 2, "hold_hours": 12},
    "signals": [
        {"pair": "GBPUSD", "direction": "SELL", "time": "2026-10-04T08:05:16Z", "status": "CLOSED",
         "result": "LOSS", "r": -1, "closed": "2026-10-05T08:05:16Z"},
        {"pair": "USDCHF", "direction": "BUY", "time": "2026-11-11T06:38:38Z", "status": "CLOSED",
         "result": "WIN", "r": 1.55, "closed": "2026-11-11T19:38:37Z"},
        {"pair": "US30", "direction": "BUY", "time": "2026-11-16T00:00:00Z", "status": "CLOSED",
         "result": "FLAT", "r": 0, "closed": "2026-11-16T12:00:00Z"},
        {"pair": "NAS100", "direction": "SELL", "time": "2026-11-17T03:38:38Z", "status": "OPEN",
         "entry": 28260, "sl": 29097.75, "tp1": 26584.5},
    ],
}

GOLD = {
    "product": "STAALWAG Gold", "pair": "XAUUSD", "unit": "pips", "signals": 9997,
    "outcomes": [{"result": "WIN", "pips": 88.0, "ts": "2026-09-20T22:01:59"},
                 {"result": "LOSS", "pips": -37.6, "ts": "2026-09-20T22:20:59"}],
    "paper_test": [
        {"rule": "breakout+trend+daily", "ts": "2026-10-20T13:02:52+13:00", "direction": "SELL",
         "entry": 4138.1, "closed_ts": "2026-10-22T13:02:52+13:00", "result": "WIN", "r": 3.0},
        {"rule": "breakout+trend+daily", "ts": "2026-10-23T15:02:19+13:00", "direction": "SELL",
         "entry": 3991.1, "closed_ts": "2026-10-23T18:42:19+13:00", "result": "LOSS", "r": -1.0},
        {"rule": "breakout+trend+daily", "ts": "2026-11-16T19:02:53+13:00", "direction": "SELL",
         "entry": 3836.2, "closed_ts": None, "result": None, "r": None},
    ],
    "swing_test": [{"symbol": "XRP-USD", "signal_t": 1793232000, "direction": "SELL",
                    "entry": 1.23, "exit_t": None, "result": None, "r": None}],
}

FX = {"product": "VELDRIN FX", "pair": "FX", "unit": "pips", "signals": 12812, "outcomes": []}


class BotStatsTest(unittest.TestCase):
    def test_r_stats(self):
        s = botstats.r_stats([1.0, -0.5, 0, None, 2.0])
        self.assertEqual((s["closed"], s["wins"], s["losses"], s["flat"]), (4, 2, 1, 1))
        self.assertEqual(s["net_r"], 2.5)
        self.assertEqual(s["pf"], 6.0)

    def test_markov_card(self):
        c = botstats.markov_card(MARKOV, now=NOW)
        self.assertEqual(c["stats"]["closed"], 3)
        self.assertEqual(c["stats"]["net_r"], 0.55)
        self.assertEqual(c["last_30d"]["closed"], 2)        # the October call is older than 30 days
        self.assertEqual(len(c["open"]), 1)
        self.assertEqual(c["open"][0]["tp"], 26584.5)       # tp1 is used when tp is missing
        self.assertEqual(c["verdict"]["level"], "early")     # 3 of 30

    def test_gold_desk_cards(self):
        cards = botstats.desk_cards("STAALWAG Gold", GOLD)
        live, paper, swing = cards
        self.assertEqual(live["stats"]["net"], 50.4)
        self.assertEqual(paper["stats"]["net_r"], 2.0)
        self.assertEqual(len(paper["open"]), 1)
        self.assertEqual(swing["stats"]["closed"], 0)
        self.assertEqual(swing["verdict"]["level"], "early")

    def test_fx_without_results_is_broken(self):
        (card,) = botstats.desk_cards("VELDRIN FX", FX)
        self.assertEqual(card["verdict"]["level"], "broken")
        self.assertIn("no trade results", card["verdict"]["text"])

    def test_unreachable_source_is_shown(self):
        def fetch(url):
            if "markov" in url:
                raise OSError("timed out")
            return GOLD if "gold" in url else FX
        out = botstats.build(fetch=fetch)
        names = [b["name"] for b in out["bots"]]
        self.assertIn("Markov bot", names)
        markov = [b for b in out["bots"] if b["name"] == "Markov bot"][0]
        self.assertEqual(markov["verdict"]["level"], "broken")


if __name__ == "__main__":
    unittest.main()
