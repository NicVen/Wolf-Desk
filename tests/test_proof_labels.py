"""Demo-account EA results must never be published as live / real money."""
import unittest

import proof_labels


def _proof():
    return {
        "headline": {"name": "STAALWAG Gold", "provenance": "live", "pf": 4.34,
                     "net_usd": 3839.92, "trades": 192, "win_rate": 55.2,
                     "note": "the anchor — real executed record"},
        "desks": [
            {"name": "STAALWAG Gold", "provenance": "live", "trades": 192, "net_usd": 3839.92,
             "note": "real EA fills — account 109223212, last 180d"},
            {"name": "STAALWAG Crypto", "provenance": "live", "trades": 0, "net_usd": 0,
             "note": "live EA — no fills in the window"},
            {"name": "VELDRIN FX — signals", "provenance": "live", "trades": 34, "net_usd": -6.9,
             "note": "dispatched signals scored on real price"},
            {"name": "Markov signal bot (raw scanner)", "provenance": "shadow", "trades": 319,
             "note": "unfiltered scanner output — research only, never traded"},
        ],
    }


class DemoLabelTest(unittest.TestCase):
    def test_demo_account_rows_and_headline_relabelled(self):
        d = proof_labels.label_demo(_proof(), ["109223212"])
        gold, crypto, sig, scan = d["desks"]
        self.assertEqual(gold["provenance"], "demo")
        self.assertTrue(gold["note"].startswith("EA fills on a demo account"))
        self.assertEqual(crypto["provenance"], "demo")
        self.assertEqual(d["headline"]["provenance"], "demo")
        self.assertIn("demo", d["headline"]["note"])
        self.assertEqual(sig["provenance"], "live")
        self.assertEqual(scan["provenance"], "shadow")

    def test_numbers_untouched(self):
        d = proof_labels.label_demo(_proof(), ["109223212"])
        self.assertEqual(d["headline"]["net_usd"], 3839.92)
        self.assertEqual(d["headline"]["trades"], 192)
        self.assertEqual(d["desks"][0]["net_usd"], 3839.92)

    def test_real_account_left_alone(self):
        d = proof_labels.label_demo(_proof(), ["999"])
        self.assertEqual(d["desks"][0]["provenance"], "live")
        self.assertEqual(d["headline"]["provenance"], "live")

    def test_idempotent(self):
        once = proof_labels.label_demo(_proof(), ["109223212"])
        twice = proof_labels.label_demo(once, ["109223212"])
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
