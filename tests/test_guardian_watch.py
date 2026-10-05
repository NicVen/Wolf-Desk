"""The MT5 watcher must warn once per new trade, with the broker's own numbers."""
import os
import tempfile
import unittest
from datetime import datetime, timezone

from guardian import watch

NOW = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)   # a Tuesday


class FakeApi:
    region = "test"

    def __init__(self):
        self.equity = 10000.0
        self.pos, self.ord = [], []
        # NAS100: tick 0.01, $0.01 per tick per lot -> $1 per point per lot
        self.ticks = {"NAS100.cash": (0.01, 0.01), "XAUUSD": (0.01, 1.0)}

    def info(self):
        return {"equity": self.equity, "balance": self.equity}

    def positions(self):
        return list(self.pos)

    def orders(self):
        return list(self.ord)

    def per_lot(self, symbol, distance):
        t = self.ticks.get(symbol)
        return distance / t[0] * t[1] if t else None


def pos(i, sym, vol, op, sl=None, typ="POSITION_TYPE_BUY"):
    return {"id": str(i), "symbol": sym, "volume": vol, "openPrice": op, "stopLoss": sl, "type": typ}


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.api, self.msgs = FakeApi(), []
        self.w = self._watcher()

    def tearDown(self):
        self.d.cleanup()

    def _watcher(self, **settings):
        s = {"risk_pct": 1, "challenge": None}
        s.update(settings)
        return watch.Watcher(self.api, s, self.msgs.append, os.path.join(self.d.name, "st.json"))

    def test_existing_trades_on_start_are_not_warned(self):
        self.api.pos = [pos(1, "XAUUSD", 1.0, 4000)]           # no stop, but already open
        self.assertEqual(self.w.tick(NOW), [])
        self.assertEqual(self.msgs, [])

    def test_nas100_without_stop_is_a_no(self):
        self.w.tick(NOW)
        self.api.pos = [pos(7, "NAS100.cash", 0.15, 25000)]
        sent = self.w.tick(NOW)
        self.assertEqual(sent[0]["verdict"], "NO")
        self.assertIn("NAS100.cash BUY 0.15 lots", self.msgs[0])
        self.assertIn("No stop loss", self.msgs[0])
        self.w.tick(NOW)                                        # same trade: no repeat
        self.assertEqual(len(self.msgs), 1)

    def test_broker_tick_value_sizes_any_symbol(self):
        self.w.tick(NOW)
        # 0.15 lots, 400-point stop, $1/point/lot = $60 = 0.6%: on plan, silent
        self.api.pos = [pos(8, "NAS100.cash", 0.15, 25000, 24600)]
        self.assertEqual(self.w.tick(NOW), [])
        # 2 lots with the same stop = $800 = 8%: NO, safe size given
        self.api.pos.append(pos(9, "NAS100.cash", 2, 25000, 24600))
        sent = self.w.tick(NOW)
        self.assertEqual(sent[0]["verdict"], "NO")
        self.assertIn("0.25 lots", self.msgs[-1])

    def test_other_open_trades_without_stops_flagged(self):
        self.api.pos = [pos(1, "XAUUSD", 0.1, 4000), pos(2, "XAUUSD", 0.1, 4000)]
        self.w.tick(NOW)
        self.api.pos.append(pos(3, "NAS100.cash", 0.1, 25000, 24900))
        sent = self.w.tick(NOW)
        self.assertEqual(sent[0]["verdict"], "NO")
        self.assertIn("2 of your open trades have no stop", self.msgs[-1])

    def test_pending_order_checked_and_fill_not_repeated(self):
        self.w.tick(NOW)
        self.api.ord = [{"id": "50", "symbol": "XAUUSD", "volume": 1, "openPrice": 4000, "stopLoss": 3990,
                         "type": "ORDER_TYPE_BUY_LIMIT"}]
        self.w.tick(NOW)
        self.assertIn("BUY limit order", self.msgs[-1])        # $1000 = 10%: NO
        self.api.ord, self.api.pos = [], [pos(50, "XAUUSD", 1, 4000, 3990)]
        self.w.tick(NOW)
        self.assertEqual(len(self.msgs), 1)

    def test_challenge_uses_todays_drop(self):
        w = self._watcher(challenge={"on": True, "start": 10000, "daily_pct": 5, "max_pct": 10})
        w.tick(NOW)                                             # day starts at $10,000
        self.api.equity = 9550.0                                # down $450 today: $50 left
        self.api.pos = [pos(4, "XAUUSD", 0.1, 4000, 3990)]      # risks $100
        w.tick(NOW)
        self.assertIn("could fail your challenge", self.msgs[-1])

    def test_state_survives_restart(self):
        self.w.tick(NOW)
        self.api.pos = [pos(7, "NAS100.cash", 0.15, 25000)]
        self.w.tick(NOW)
        self.assertEqual(len(self._watcher().tick(NOW)), 0)

    def test_metaapi_reads_region_and_tick_value(self):
        calls = []

        def get(url, token=None, data=None, timeout=20):
            calls.append(url)
            self.assertEqual(token, "tok")
            if "provisioning" in url:
                return {"region": "london"}
            if url.endswith("/specification"):
                return {"tickSize": 0.01}
            if url.endswith("/current-price"):
                return {"lossTickValue": 0.01, "profitTickValue": 0.01}
            return {}

        api = watch.MetaApi("tok", "acc1", get=get)
        self.assertEqual(api.region, "london")
        self.assertAlmostEqual(api.per_lot("NAS100.cash", 400), 400)    # $1 per point per lot
        self.assertIn("mt-client-api-v1.london.agiliumtrade.ai/users/current/accounts/acc1/symbols/NAS100.cash/", calls[-1])
        api.per_lot("NAS100.cash", 10)
        self.assertEqual(sum(u.endswith("/specification") for u in calls), 1)   # spec cached

    def test_order_type_names(self):
        self.assertEqual(watch.describe({"type": "ORDER_TYPE_SELL_STOP_LIMIT"}), "SELL stop limit order")
        self.assertEqual(watch.describe({"type": "POSITION_TYPE_SELL"}), "SELL")


if __name__ == "__main__":
    unittest.main()
