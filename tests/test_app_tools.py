import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_tools  # noqa: E402
from guardian import live  # noqa: E402

D = app_tools.DAY


class Tiles(unittest.TestCase):
    def t(self, day, trial=False, valid=True, hours=False, guard=False, sale=("HOURS", "GUARDIAN")):
        return app_tools.tiles(valid, trial, 1000, hours, guard, 1000 + day * D, sale)

    def test_trial_and_bad_keys_see_no_tools(self):
        none = {"sizer": None, "hours": None, "guardian": None}
        self.assertEqual(self.t(30, trial=True), none)
        self.assertEqual(self.t(30, valid=False), none)

    def test_revealed_after_purchase(self):
        self.assertEqual(self.t(0), {"sizer": "free", "hours": None, "guardian": None})
        self.assertEqual(self.t(6.9)["hours"], None)
        self.assertEqual(self.t(7), {"sizer": "free", "hours": "available", "guardian": "soon"})
        self.assertEqual(self.t(11.9)["guardian"], "soon")
        self.assertEqual(self.t(12), {"sizer": "free", "hours": "available", "guardian": "available"})

    def test_not_for_sale_stays_coming_soon(self):
        self.assertEqual(self.t(30, sale=()), {"sizer": "free", "hours": "soon", "guardian": "soon"})

    def test_rented_add_ons_always_open(self):
        self.assertEqual(self.t(0, hours=True, guard=True), {"sizer": "free", "hours": "open", "guardian": "open"})
        self.assertEqual(self.t(0, trial=True, guard=True)["guardian"], "open")


class OneAccountPerKey(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.d.cleanup()

    def test_first_account_claims_the_key(self):
        d = self.d.name
        self.assertTrue(live.claim_account("K", "7200717", d=d, now=1000))
        self.assertTrue(live.claim_account("K", "7200717", d=d, now=1010))
        self.assertFalse(live.claim_account("K", "5550001", d=d, now=1020))   # a shared key
        self.assertTrue(live.claim_account("K", "", d=d))                     # no login sent
        self.assertIsNotNone(live.release_account("K", d=d, now=1000 + 3600))  # once a day only
        self.assertIsNone(live.release_account("K", d=d, now=1000 + live.SWITCH_WAIT))
        self.assertTrue(live.claim_account("K", "5550001", d=d, now=1000 + live.SWITCH_WAIT + 5))
        self.assertFalse(live.claim_account("K", "7200717", d=d, now=1000 + live.SWITCH_WAIT + 6))
        self.assertEqual(live.linked_account("K", d=d), "5550001")


if __name__ == "__main__":
    unittest.main()
