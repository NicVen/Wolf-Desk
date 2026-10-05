"""Prime Hours must find the busy and quiet hours from real-shaped bars."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from scout import hours


def _bars(days=40, busy=(13, 14, 15, 16), quiet=(22, 23, 0), weekend=False):
    """Synthetic hourly bars: 1% range in busy hours, 0.1% in quiet ones,
    0.4% otherwise. Wednesdays move twice as much."""
    t0 = datetime(2026, 1, 5, tzinfo=timezone.utc)   # a Monday
    times, highs, lows, closes = [], [], [], []
    for d in range(days):
        day = t0 + timedelta(days=d)
        if day.weekday() >= 5 and not weekend:
            continue
        for h in range(24):
            r = 1.0 if h in busy else 0.1 if h in quiet else 0.4
            if day.weekday() == 2:
                r *= 2
            ts = int((day + timedelta(hours=h)).timestamp())
            times.append(ts); closes.append(100.0)
            highs.append(100 + r / 2); lows.append(100 - r / 2)
    return times, highs, lows, closes


class ProfileTest(unittest.TestCase):
    def test_prime_and_dead_windows(self):
        p = hours.profile(*_bars())
        self.assertEqual(p["hours"][14], 100)
        self.assertIn(p["prime"]["start"], (13, 14))
        self.assertIn(p["dead"]["start"], (22, 23))
        self.assertLess(p["hours"][23], 20)

    def test_best_day_and_no_weekend(self):
        p = hours.profile(*_bars())
        days = {d["day"]: d["score"] for d in p["days"]}
        self.assertEqual(days["Wed"], 100)
        self.assertNotIn("Sat", days)
        self.assertEqual(len(days), 5)

    def test_bad_bars_skipped_and_short_history_refused(self):
        t, h, l, c = _bars()
        h[0], l[0], c[0] = None, None, None          # Yahoo gaps arrive as None
        self.assertIsNotNone(hours.profile(t, h, l, c))
        self.assertIsNone(hours.profile(*_bars(days=10)))

    def test_prime_window_wraps_midnight(self):
        p = hours.profile(*_bars(busy=(23, 0, 1), quiet=(10, 11, 12)))
        self.assertIn(p["prime"]["start"], (22, 23))
        self.assertEqual(p["prime"]["end"], (p["prime"]["start"] + 3) % 24)

    def test_build_keeps_old_profile_when_fetch_fails(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "ph.json")
            with open(out, "w") as f:
                json.dump({"symbols": {"GC=F": {"name": "Gold", "hours": [1] * 24}}}, f)
            with mock.patch.object(hours, "_app_symbols", return_value={"GC=F": "Gold", "SI=F": "Silver"}), \
                 mock.patch.object(hours, "_fetch", side_effect=lambda t: (_ for _ in ()).throw(OSError("blocked")) if t == "GC=F" else _bars()):
                data = hours.build(out=out, pause=0)
            self.assertEqual(data["symbols"]["GC=F"]["hours"], [1] * 24)
            self.assertEqual(data["symbols"]["SI=F"]["name"], "Silver")


if __name__ == "__main__":
    unittest.main()
