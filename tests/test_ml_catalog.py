import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from collectors.base import SourceError
from collectors.mercadolivre import MercadoLivreSource
from database.models import connect
from services.discount_filter import evaluate
from config import Config
from services.price_history import record_price


@patch("collectors.mercadolivre.secret", return_value="test-token")
class CatalogTests(unittest.TestCase):
    def source(self, db):
        client = Mock()
        client.health.return_value = {"state": "ready_to_validate"}
        return MercadoLivreSource(db, {"api_resource": "catalog"}, client=client), client

    def product(self):
        return {"id": "MLB19444510", "status": "active", "name": "Processador AMD Ryzen 5 5500"}

    def item(self):
        return {"item_id": "MLB123", "site_id": "MLB", "currency_id": "BRL", "seller_id": 42,
                "price": 582, "original_price": 799, "condition": "new", "official_store_id": 1}

    def entry(self):
        return {"id": "ml-MLB123", "catalog_id": "MLB19444510",
                "url": "https://www.mercadolivre.com.br/p/MLB19444510?pdp_filters=item_id%3AMLB123"}

    def test_prices_are_specific_to_seller_and_unknown_stock_blocks_publication(self, secret):
        with closing(connect(":memory:")) as db:
            source, client = self.source(db)
            client.get.side_effect = [self.product(), {"results": [self.item()]}]
            offer = source.collect(self.entry())
            self.assertEqual((offer.price_cents, offer.seller_id), (58200, "42"))
            self.assertEqual(offer.source, "official_catalog")
            self.assertEqual(offer.official_store_id, 1)
            self.assertEqual(offer.price_basis, "catalog_item_price")
            self.assertFalse(offer.available)
            now = datetime.now(timezone.utc)
            for days in (1, 2, 3):
                record_price(db, offer.store, offer.product_id, 80000, now - timedelta(days=days))
            config = Config(trusted_sellers=frozenset({("mercadolivre", "42")}))
            decision = evaluate(db, offer, config, now)
            self.assertEqual(decision.status, "pending_review")
            self.assertEqual(decision.reasons, ("Oferta indisponível",))
            self.assertTrue(all("/products/" in call.args[0] for call in client.get.call_args_list))

    def test_manual_link_has_no_silent_item_endpoint_fallback(self, secret):
        with closing(connect(":memory:")) as db:
            source, client = self.source(db)
            entry = self.entry()
            del entry["catalog_id"]
            with self.assertRaises(SourceError) as caught:
                source.collect(entry)
            self.assertEqual(caught.exception.state, "catalog_mapping_required")
            client.get.assert_not_called()

    def test_buy_box_stock_must_match_exact_offer(self, secret):
        with closing(connect(":memory:")) as db:
            source, client = self.source(db)
            product = self.product()
            winner = dict(self.item(), available_quantity=2)
            product["buy_box_winner"] = winner
            client.get.side_effect = [product, {"results":[self.item()]}]
            self.assertTrue(source.collect(self.entry()).available)
            for changes in ({"item_id":"MLB999"}, {"seller_id":99}, {"price":1},
                            {"currency_id":"USD"}, {"available_quantity":0}):
                product["buy_box_winner"] = dict(winner, **changes)
                client.get.side_effect = [product, {"results":[self.item()]}]
                self.assertFalse(source.collect(self.entry()).available)
            product["buy_box_winner"] = winner
            for changes in ({"available_quantity":0}, {"status":"paused"}, {"condition":"used"}):
                client.get.side_effect = [product, {"results":[dict(self.item(), **changes)]}]
                self.assertFalse(source.collect(self.entry()).available)

    def test_missing_item_and_wrong_currency_are_rejected(self, secret):
        with closing(connect(":memory:")) as db:
            source, client = self.source(db)
            client.get.side_effect = [self.product(), {"results": []}]
            with self.assertRaises(SourceError) as caught:
                source.collect(self.entry())
            self.assertEqual(caught.exception.state, "catalog_item_missing")
            item = self.item()
            item["currency_id"] = "USD"
            client.get.side_effect = [self.product(), {"results": [item]}]
            with self.assertRaises(SourceError):
                source.collect(self.entry())

    def test_search_skips_empty_catalog_but_not_permission_denial(self, secret):
        with closing(connect(":memory:")) as db:
            source, client = self.source(db)
            client.get.side_effect = [{"results": [self.product()]}, SourceError("not_found", "404")]
            self.assertEqual(source.search("processador", 5), [])
            client.get.side_effect = [{"results": [self.product()]}, SourceError("access_denied", "403")]
            with self.assertRaises(SourceError) as caught:
                source.search("processador", 5)
            self.assertEqual(caught.exception.state, "access_denied")

    def test_search_preserves_selected_item_and_catalog_mapping(self, secret):
        with closing(connect(":memory:")) as db:
            source, client = self.source(db)
            client.get.side_effect = [{"results": [self.product()]}, {"results": [self.item()]}]
            entries = source.search("processador", 5)
            self.assertEqual(entries[0]["catalog_id"], "MLB19444510")
            self.assertEqual(entries[0]["id"], "ml-MLB123")
            self.assertIn("MLB123", entries[0]["url"])

    def test_catalog_health_does_not_reset_denied_items(self, secret):
        with closing(connect(":memory:")) as db:
            old = MercadoLivreSource(db, {})
            old.client.fail("access_denied")
            catalog = MercadoLivreSource(db, {"api_resource": "catalog"})
            self.assertEqual(catalog.status()["state"], "ready_to_validate")
            self.assertEqual(old.status()["state"], "access_denied")


if __name__ == "__main__":
    unittest.main()
