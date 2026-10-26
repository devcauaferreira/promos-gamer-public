import json
import os
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from collectors.mercadolivre import MercadoLivreSource
from config import Config
from database.models import Offer, connect
from services.discount_filter import evaluate
from services.price_history import record_price
from services.price_observations import record_observation
from services.runner import cycle


class PriceObservations(unittest.TestCase):
    def offer(self, **changes):
        value = Offer("mercadolivre", "ml-MLB123:context", "Processador AMD Ryzen 5 5500",
                      "42", 38000, None, "Preço do catálogo; confira pagamento na loja", False,
                      "https://www.mercadolivre.com.br/p/MLB19444510?pdp_filters=item_id%3AMLB123",
                      source="official_catalog", price_basis="catalog_item_price",
                      official_store_id=1, availability_evidence="unknown")
        return replace(value, **changes)

    def test_daily_observation_preserves_original_time_and_only_newer_data(self):
        original = datetime(2026, 10, 25, 23, 30, tzinfo=timezone(timedelta(hours=-3)))
        with closing(connect(":memory:")) as db:
            record_observation(db, self.offer(), original)
            record_observation(db, self.offer(price_cents=80000), original - timedelta(minutes=1))
            row = db.execute("""SELECT day, price_cents, observed_at, source, seller_id,
                payment_terms, price_basis, available, availability_evidence
                FROM price_observations""").fetchone()
            self.assertEqual(row, ("2026-10-26", 38000, original.astimezone(timezone.utc).isoformat(),
                                   "official_catalog", "42", self.offer().payment_terms,
                                   "catalog_item_price", 0, "unknown"))
            newer = original + timedelta(minutes=1)
            record_observation(db, self.offer(price_cents=37000, available=True,
                                             availability_evidence="quantity"), newer)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT price_cents, available, availability_evidence FROM price_observations").fetchone(),
                             (37000, 1, "quantity"))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM prices").fetchone()[0], 0)

    def test_observations_are_not_discount_history(self):
        now = datetime.now(timezone.utc)
        with closing(connect(":memory:")) as db:
            record_observation(db, self.offer(price_cents=80000), now - timedelta(days=1))
            decision = evaluate(db, self.offer(available=True, availability_evidence="quantity"), Config(), now)
            self.assertIsNone(decision.average_cents)
            self.assertIn("Histórico insuficiente", decision.reasons)
            self.assertEqual(decision.status, "pending_review")

    def test_invalid_values_cannot_be_recorded(self):
        now = datetime.now(timezone.utc)
        with closing(connect(":memory:")) as db:
            for changes in ({"price_cents": 0}, {"price_cents": True}, {"seller_id": ""},
                            {"source": ""}, {"payment_terms": " "}, {"price_basis": ""},
                            {"product_id": ""}, {"available": 1}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    record_observation(db, self.offer(**changes), now)
            with self.assertRaises(ValueError):
                record_observation(db, self.offer(), now.replace(tzinfo=None))

    def test_runner_records_unknown_catalog_stock_without_price_history_or_send(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                entry = {"id": "ml-MLB123", "store": "mercadolivre", "catalog_id": "MLB19444510",
                         "url": self.offer().affiliate_url, "enabled": True}
                Path("products.json").write_text(json.dumps([entry]), encoding="utf-8")
                config = Config(database_path=Path("prices.sqlite3"))
                settings = {"whatsapp_group_id": "test@g.us", "discovery": {"enabled": False}}
                client = Mock()
                client.health.return_value = {"state": "ready_to_validate"}
                client.get.side_effect = lambda url, **kwargs: (
                    {"id": "MLB19444510", "status": "active", "name": self.offer().title}
                    if not "/items?" in url else
                    {"results": [{"item_id": "MLB123", "site_id": "MLB", "currency_id": "BRL",
                                  "seller_id": 42, "price": 380, "condition": "new", "official_store_id": 1}]})
                with closing(connect(config.database_path)) as db, \
                     patch("collectors.mercadolivre.secret", return_value="test-token"):
                    source = MercadoLivreSource(db, {"api_resource": "catalog"}, client=client)
                with patch("services.runner.load_settings", return_value=(config, settings)), \
                     patch("services.runner.build_sources", return_value={"mercadolivre": source}), \
                     patch("services.runner.source_report", return_value=[]), \
                     patch("services.runner.publish") as publish:
                    initial = cycle(send=True)[0]
                    self.assertFalse(initial["offer"]["available"])
                    self.assertEqual(initial["offer"]["availability_evidence"], "unknown")
                    product_id = initial["offer"]["product_id"]
                    self.assertTrue(product_id.startswith("ml-MLB123:"))
                    with closing(connect(config.database_path)) as db:
                        self.assertEqual(db.execute("SELECT product_id, available, availability_evidence FROM price_observations").fetchone(),
                                         (product_id, 0, "unknown"))
                        self.assertEqual(db.execute("SELECT COUNT(*) FROM prices").fetchone()[0], 0)
                        record_price(db, "mercadolivre", product_id, 80000, datetime.now(timezone.utc) - timedelta(days=1))
                    repeated = cycle(send=True)[0]
                    self.assertEqual(repeated["decision"]["reasons"], ("Disponibilidade não confirmada",))
                    self.assertEqual(repeated["decision"]["status"], "pending_review")
                    with closing(connect(config.database_path)) as db:
                        self.assertEqual(db.execute("SELECT COUNT(*) FROM prices").fetchone()[0], 1)
                    publish.assert_not_called()
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
