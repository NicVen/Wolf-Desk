"""Guardian must say NO to the trades that blow accounts, and only those."""
import unittest
from datetime import datetime, timezone

from guardian import rules

# Tuesday 14:00 UTC: markets open
NOW = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)
ACC = {"equity": 10000, "risk_pct": 1}
GOLD_HOURS = {"hours": [10] * 6 + [60] * 6 + [100] * 6 + [30] * 6,
              "prime": {"start": 12, "end": 15}, "dead": {"start": 2, "end": 5}}


def gold(lots, stop=10):
    return {"sym": "XAUUSD", "lots": lots, "stop": stop}


def kinds(r, level):
    return [c["kind"] for c in r["checks"] if c["level"] == level]


class GuardianTest(unittest.TestCase):
    def test_on_plan_trade_is_ok(self):
        # 0.10 lots gold, $10 stop = $100 = 1% of $10k
        r = rules.check(gold(0.10), ACC, NOW, events=[], hours=GOLD_HOURS)
        self.assertEqual(r["verdict"], "OK")
        self.assertAlmostEqual(r["risk_usd"], 100)
        self.assertEqual(r["safe_lots"], 0.10)

    def test_oversized_trade_is_no_with_safe_size(self):
        r = rules.check(gold(0.50), ACC, NOW, hours=GOLD_HOURS)
        self.assertEqual(r["verdict"], "NO")
        self.assertIn("size", kinds(r, "NO"))
        self.assertIn("0.10 lots", r["checks"][0]["text"])

    def test_a_bit_over_plan_is_careful(self):
        r = rules.check(gold(0.12), ACC, NOW, hours=GOLD_HOURS)
        self.assertEqual(r["verdict"], "CAREFUL")

    def test_no_stop_is_no(self):
        r = rules.check(gold(0.10, stop=0), ACC, NOW)
        self.assertEqual(r["verdict"], "NO")

    def test_usdjpy_needs_price_and_divides_by_it(self):
        t = {"sym": "USDJPY", "lots": 0.5, "stop": 30, "price": 150}
        r = rules.check(t, ACC, NOW)
        self.assertAlmostEqual(r["risk_usd"], 100)       # 30 pips x 1000 JPY / 150
        r = rules.check({"sym": "USDJPY", "lots": 0.5, "stop": 30}, ACC, NOW)
        self.assertEqual(kinds(r, "CAREFUL"), ["size"])

    def test_seven_open_trades_too_much_heat(self):
        acc = dict(ACC, open_trades=7, open_risk=600)
        r = rules.check(gold(0.10), acc, NOW, hours=GOLD_HOURS)
        self.assertEqual(r["verdict"], "NO")
        self.assertIn("heat", kinds(r, "NO"))

    def test_challenge_daily_limit(self):
        ch = {"on": True, "start": 10000, "daily_pct": 5, "max_pct": 10, "today_pl": -420}
        # $80 left today; a $100 risk could end the challenge
        r = rules.check(gold(0.10), dict(ACC, challenge=ch), NOW, hours=GOLD_HOURS)
        self.assertIn("challenge", kinds(r, "NO"))
        ch["today_pl"] = -500
        r = rules.check(gold(0.01), dict(ACC, challenge=ch), NOW, hours=GOLD_HOURS)
        self.assertIn("challenge", kinds(r, "NO"))
        ch["today_pl"] = 0
        r = rules.check(gold(0.10), dict(ACC, challenge=ch), NOW, hours=GOLD_HOURS)
        self.assertIn("challenge", kinds(r, "OK"))

    def test_news_now_is_no_later_is_careful_other_currency_ignored(self):
        def ev(mins, cur="USD", impact="High"):
            return {"ts": NOW.timestamp() + mins * 60, "currency": cur, "impact": impact, "title": "CPI"}
        r = rules.check(gold(0.10), ACC, NOW, events=[ev(12)])
        self.assertIn("news", kinds(r, "NO"))
        self.assertIn("12 min", [c for c in r["checks"] if c["kind"] == "news"][0]["text"])
        r = rules.check(gold(0.10), ACC, NOW, events=[ev(-5)])
        self.assertIn("news", kinds(r, "NO"))
        r = rules.check(gold(0.10), ACC, NOW, events=[ev(120)])
        self.assertIn("news", kinds(r, "CAREFUL"))
        r = rules.check(gold(0.10), ACC, NOW, events=[ev(12, cur="JPY"), ev(12, impact="Low")])
        self.assertIn("news", kinds(r, "OK"))
        r = rules.check({"sym": "USDJPY", "lots": 0.5, "stop": 30, "price": 150}, ACC, NOW, events=[ev(12, cur="JPY")])
        self.assertIn("news", kinds(r, "NO"))

    def test_dead_zone_and_weekend(self):
        r = rules.check(gold(0.10), ACC, NOW.replace(hour=3), hours=GOLD_HOURS)
        self.assertIn("time", kinds(r, "CAREFUL"))
        sat = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
        self.assertIn("time", kinds(rules.check(gold(0.10), ACC, sat), "NO"))
        self.assertEqual(kinds(rules.check({"sym": "BTCUSD", "lots": 0.1, "stop": 1000}, ACC, sat), "NO"), [])

    def test_bad_input(self):
        self.assertIn("error", rules.check({"sym": "XYZ"}, ACC, NOW))
        self.assertIn("error", rules.check(gold(0), ACC, NOW))
        self.assertIn("error", rules.check(gold(0.1), {"equity": "abc"}, NOW))

    def test_calendar_time_parse(self):
        self.assertEqual(rules.parse_event_time("2026-10-06T10:00:00-04:00"),
                         datetime(2026, 10, 6, 14, tzinfo=timezone.utc).timestamp())
        self.assertIsNone(rules.parse_event_time(""))


if __name__ == "__main__":
    unittest.main()
