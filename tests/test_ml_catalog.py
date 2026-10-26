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
            offer = source.collect(dict(self.entry(), availability_verified=True))
            self.assertEqual((offer.price_cents, offer.seller_id), (58200, "42"))
            self.assertEqual(offer.source, "official_catalog")
            self.assertEqual(offer.official_store_id, 1)
            self.assertEqual(offer.price_basis, "catalog_item_price")
            self.assertFalse(offer.available)
            self.assertEqual(offer.availability_evidence, "unknown")
            now = datetime.now(timezone.utc)
            for days in (1, 2, 3):
                record_price(db, offer.store, offer.product_id, 80000, now - timedelta(days=days))
            config = Config(trusted_sellers=frozenset({("mercadolivre", "42")}))
            decision = evaluate(db, offer, config, now)
            self.assertEqual(decision.status, "pending_review")
            self.assertEqual(decision.reasons, ("Disponibilidade não confirmada",))
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
            offer = source.collect(self.entry())
            self.assertTrue(offer.available)
            self.assertEqual(offer.availability_evidence, "buy_box_winner")
            for changes in ({"item_id":"MLB999"}, {"seller_id":99}, {"price":1},
                            {"currency_id":"USD"}, {"available_quantity":0}):
                product["buy_box_winner"] = dict(winner, **changes)
                client.get.side_effect = [product, {"results":[self.item()]}]
                self.assertFalse(source.collect(self.entry()).available)
            product["buy_box_winner"] = winner
            for changes in ({"available_quantity":0}, {"status":"paused"}, {"condition":"used"}):
                client.get.side_effect = [product, {"results":[dict(self.item(), **changes)]}]
                self.assertFalse(source.collect(self.entry()).available)

    def test_declared_catalog_stock_records_its_evidence(self, secret):
        with closing(connect(":memory:")) as db:
            source, client = self.source(db)
            client.get.side_effect = [self.product(), {"results": [dict(self.item(), status="active", available_quantity=1)]}]
            offer = source.collect(self.entry())
            self.assertTrue(offer.available)
            self.assertEqual(offer.availability_evidence, "quantity")

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
            client.get.side_effect = [{"results": [self.product()]}, self.product(), SourceError("not_found", "404")]
            self.assertEqual(source.search("processador", 5), [])
            client.get.side_effect = [{"results": [self.product()]}, self.product(), SourceError("access_denied", "403")]
            with self.assertRaises(SourceError) as caught:
                source.search("processador", 5)
            self.assertEqual(caught.exception.state, "access_denied")

    def test_search_preserves_selected_item_and_catalog_mapping(self, secret):
        with closing(connect(":memory:")) as db:
            source, client = self.source(db)
            client.get.side_effect = [{"results": [self.product()]}, self.product(), {"results": [self.item()]}]
            entries = source.search("processador", 5)
            self.assertEqual(entries[0]["catalog_id"], "MLB19444510")
            self.assertEqual(entries[0]["id"], "ml-MLB123")
            self.assertIn("MLB123", entries[0]["url"])

    def test_search_uses_verified_hardware_domain_and_bounded_sample(self, secret):
        from urllib.parse import parse_qs, urlparse
        with closing(connect(':memory:')) as db:
            source, client = self.source(db)
            client.get.return_value = {'results': []}
            source.search('fonte', 20)
            query = parse_qs(urlparse(client.get.call_args.args[0]).query)
            self.assertEqual(query['domain_id'], ['MLB-DESKTOP_COMPUTER_POWER_SUPPLIES'])
            self.assertEqual(query['limit'], ['5'])

    def test_catalog_excludes_bulk_or_used_listing(self, secret):
        with closing(connect(":memory:")) as db:
            source, client = self.source(db)
            client.get.side_effect = [{"results": [self.product()]}, self.product(),
                                      {"results": [dict(self.item(), min_purchase_unit=2),
                                                   dict(self.item(), condition="used")]}]
            self.assertEqual(source.search("processador", 5), [])
            client.get.side_effect = [self.product(),
                                      {"results": [dict(self.item(), min_purchase_unit=2)]}]
            with self.assertRaises(SourceError) as caught:
                source.collect(self.entry())
            self.assertEqual(caught.exception.state, "wholesale_review")

    def test_discovery_interleaves_products_instead_of_filling_with_first_catalog(self, secret):
        products = [dict(self.product(), id="MLB" + str(100 + index)) for index in range(3)]
        listings = [[dict(self.item(), item_id="MLB" + str(1000 + product * 100 + item))
                     for item in range(20)] for product in range(3)]
        with closing(connect(":memory:")) as db:
            source, client = self.source(db)
            client.get.side_effect = [{"results": products},
                                      products[0], {"results": listings[0]},
                                      products[1], {"results": listings[1]},
                                      products[2], {"results": listings[2]}]
            entries = source.search("processador", 5)
            self.assertEqual([entry["catalog_id"] for entry in entries],
                             ["MLB100", "MLB101", "MLB102", "MLB100", "MLB101"])
            self.assertEqual([entry["id"] for entry in entries],
                             ["ml-MLB1000", "ml-MLB1100", "ml-MLB1200", "ml-MLB1001", "ml-MLB1101"])
            self.assertTrue(all(entry["availability_verified"] is False for entry in entries))

    def test_discovery_prefers_verified_winner_from_later_product(self, secret):
        first = self.product()
        chosen = dict(self.item(), item_id="MLB999")
        second = dict(self.product(), id="MLB19444511", buy_box_winner=dict(chosen, available_quantity=2))
        with closing(connect(":memory:")) as db:
            source, client = self.source(db)
            client.get.side_effect = [{"results": [first, second]},
                                      first, {"results": [self.item()]},
                                      second, {"results": [chosen]}]
            entries = source.search("processador", 1)
            self.assertEqual(entries[0]["id"], "ml-MLB999")
            self.assertEqual(entries[0]["catalog_id"], second["id"])
            self.assertIs(entries[0]["availability_verified"], True)
            client.get.side_effect = [second, {"results": [chosen]}]
            offer = source.collect(entries[0])
            self.assertTrue(offer.available)
            self.assertEqual(offer.availability_evidence, "buy_box_winner")

    def test_discovery_never_prioritizes_a_contradictory_winner(self, secret):
        valid = dict(self.item(), item_id="MLB999")
        second = dict(self.product(), id="MLB19444511", buy_box_winner=dict(valid, available_quantity=2))
        cases = [(self.item(), changes) for changes in (
            {"item_id": "MLB888"}, {"seller_id": 99}, {"price": 1},
            {"currency_id": "USD"}, {"available_quantity": 0})]
        cases += [(dict(self.item(), **changes), {}) for changes in (
            {"status": "paused"}, {"available_quantity": 0}, {"condition": "used"})]
        for item, winner_changes in cases:
            with self.subTest(item=item, winner_changes=winner_changes), closing(connect(":memory:")) as db:
                source, client = self.source(db)
                winner = dict(dict(self.item(), available_quantity=2), **winner_changes)
                first = dict(self.product(), buy_box_winner=winner)
                client.get.side_effect = [{"results": [first, second]},
                                          first, {"results": [item]},
                                          second, {"results": [valid]}]
                self.assertEqual(source.search("processador", 1)[0]["id"], "ml-MLB999")

    def test_discovery_prioritizes_declared_quantity_and_rejects_wrong_detail_identity(self, secret):
        with closing(connect(":memory:")) as db:
            source, client = self.source(db)
            quantity = dict(self.item(), item_id="MLB999", status="active", available_quantity=1)
            client.get.side_effect = [{"results": [self.product()]}, self.product(),
                                      {"results": [self.item(), dict(quantity, price=0),
                                                   dict(quantity, currency_id="USD"),
                                                   dict(quantity, seller_id=0),
                                                   dict(quantity, official_store_id=0), quantity]}]
            self.assertEqual(source.search("processador", 1)[0]["id"], "ml-MLB999")
            client.get.side_effect = [{"results": [self.product()]}, dict(self.product(), id="MLB999")]
            with self.assertRaises(SourceError) as caught:
                source.search("processador", 1)
            self.assertEqual(caught.exception.state, "invalid_response")

    def test_discovery_bounds_product_details_and_output_even_if_api_returns_more(self, secret):
        products = [dict(self.product(), id="MLB" + str(100 + index)) for index in range(12)]
        with closing(connect(":memory:")) as db:
            source, client = self.source(db)
            source.options["catalog_products_per_category"] = 999
            def response(url, **kwargs):
                if "/products/search?" in url:
                    return {"results": products}
                pid = url.split("/products/", 1)[1].split("/", 1)[0]
                if "/items?" in url:
                    return {"results": [dict(self.item(), item_id=pid + str(index)) for index in range(3)]}
                return next(product for product in products if product["id"] == pid)
            client.get.side_effect = response
            entries = source.search("processador", 999)
            self.assertEqual(len(entries), 20)
            details = [call for call in client.get.call_args_list
                       if "/search?" not in call.args[0] and "/items?" not in call.args[0]]
            self.assertEqual(len(details), 10)
            self.assertEqual(len({entry["catalog_id"] for entry in entries}), 10)
            client.reset_mock()
            self.assertEqual(source.search("processador", 0), [])
            client.get.assert_not_called()
            self.assertEqual(source.discovery_version, "hardware-domains-v3")

    def test_catalog_health_does_not_reset_denied_items(self, secret):
        with closing(connect(":memory:")) as db:
            old = MercadoLivreSource(db, {})
            old.client.fail("access_denied")
            catalog = MercadoLivreSource(db, {"api_resource": "catalog"})
            self.assertEqual(catalog.status()["state"], "ready_to_validate")
            self.assertEqual(old.status()["state"], "access_denied")


if __name__ == "__main__":
    unittest.main()
