import io
import json
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from collectors.base import SourceError
from collectors.feed import AuthorizedFeed
from collectors.mercadolivre import MercadoLivreSource
from collectors.registry import build_sources, LazyBrowser
from database.models import connect
from services.diagnostics import response_metadata
from services.http_client import JsonHttpClient, retry_seconds


def response(data):
    value = Mock(status=200, headers={"Content-Type": "application/json"})
    value.read.return_value = json.dumps(data).encode()
    value.__enter__ = Mock(return_value=value)
    value.__exit__ = Mock(return_value=False)
    return value


def failure(status, headers=None):
    return HTTPError("https://api.mercadolibre.com/items/MLB123", status, "error",
                     headers or {"Content-Type": "application/json"}, io.BytesIO(b'{"error":"forbidden"}'))


class TransportTests(unittest.TestCase):
    @patch("services.http_client.write_diagnostic")
    def test_403_persists_and_force_does_not_repeat(self, log):
        opener = Mock()
        opener.open.side_effect = failure(403)
        with closing(connect(":memory:")) as db:
            client = JsonHttpClient(db, "mercadolivre", "scope", opener=opener)
            with self.assertRaises(SourceError) as error:
                client.get("https://api.mercadolibre.com/items/MLB123")
            self.assertEqual(error.exception.state, "access_denied")
            restarted = JsonHttpClient(db, "mercadolivre", "scope", opener=opener)
            with self.assertRaises(SourceError):
                restarted.get("https://api.mercadolibre.com/items/MLB123")
            self.assertEqual(opener.open.call_count, 1)

    @patch("services.http_client.write_diagnostic")
    def test_429_respects_retry_after_without_worker_sleep(self, log):
        opener, sleep = Mock(), Mock()
        opener.open.side_effect = failure(429, {"Retry-After": "3600"})
        with closing(connect(":memory:")) as db:
            client = JsonHttpClient(db, "mercadolivre", "scope", opener=opener, sleep=sleep)
            with self.assertRaises(SourceError):
                client.get("https://api.mercadolibre.com/items/MLB123")
            health = client.health()
            self.assertEqual(health["state"], "rate_limited")
            self.assertGreater(datetime.fromisoformat(health["retry_at"]), datetime.now(timezone.utc) + timedelta(minutes=59))
            sleep.assert_not_called()

    @patch("services.http_client.write_diagnostic")
    def test_503_has_bounded_retries_then_recovers(self, log):
        opener, sleep = Mock(), Mock()
        opener.open.side_effect = [failure(503), failure(503), response({"id": "MLB123"})]
        with closing(connect(":memory:")) as db:
            client = JsonHttpClient(db, "mercadolivre", "scope", opener=opener, sleep=sleep)
            self.assertEqual(client.get("https://api.mercadolibre.com/items/MLB123"), {"id": "MLB123"})
            self.assertEqual(opener.open.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(client.health()["state"], "operational")

    def test_diagnostics_exclude_secrets_cookies_and_raw_body(self):
        metadata = response_metadata("https://user:password@example.com/items?access_token=SECRET", 403,
                                     {"Content-Type": "application/json", "Set-Cookie": "private=COOKIE"},
                                     b'{"message":"Name Email SECRET", "error":"SECRET"}')
        text = json.dumps(metadata)
        for sensitive in ("password", "SECRET", "COOKIE", "Email", "access_token"):
            self.assertNotIn(sensitive, text)
        self.assertEqual(metadata["url"], "https://example.com/items")
        self.assertEqual(retry_seconds("120"), 120)


class AdapterTests(unittest.TestCase):
    @patch("collectors.mercadolivre.secret", return_value="")
    def test_missing_token_never_calls_api_or_browser(self, secret):
        client, browser = Mock(), Mock()
        with closing(connect(":memory:")) as db:
            source = MercadoLivreSource(db, {}, client=client)
            with self.assertRaises(SourceError):
                source.collect({"url": "https://produto.mercadolivre.com.br/MLB-123-_JM", "id": "ml-MLB123"})
            client.get.assert_not_called()
            sources = build_sources(db, {}, browser)
            self.assertEqual(sources["amazon"].status()["state"], "needs_authorized_feed")
            self.assertEqual(sources["mercadolivre"].status()["state"], "needs_credentials")
            browser.new_page.assert_not_called()

    @patch("collectors.mercadolivre.secret", return_value="test-token")
    def test_api_mapping_and_variant_review(self, secret):
        client = Mock()
        client.health.return_value = {"state": "ready_to_validate"}
        item = {"id": "MLB123", "currency_id": "BRL", "seller_id": 42, "title": "Processador AMD Ryzen 5500",
                "price": 380.00, "status": "active", "condition": "new", "available_quantity": 1,
                "permalink": "https://produto.mercadolivre.com.br/MLB-123-_JM"}
        client.get.return_value = item
        with closing(connect(":memory:")) as db:
            source = MercadoLivreSource(db, {}, client=client)
            entry = {"url": item["permalink"], "id": "ml-MLB123"}
            offer = source.collect(entry)
            self.assertEqual(offer.price_cents, 38000)
            self.assertEqual(offer.seller_id, "42")
            self.assertEqual(offer.source, "official_api")
            self.assertTrue(offer.available)
            self.assertEqual(offer.availability_evidence, "quantity")
            client.get.assert_called_once()
            item["min_purchase_unit"] = 2
            self.assertFalse(source.collect(entry).available)
            item.pop("min_purchase_unit")
            item["variations"] = [{"id": 1}]
            with self.assertRaises(SourceError) as error:
                source.collect(entry)
            self.assertEqual(error.exception.state, "variant_review")

    def test_feed_freshness_and_explicit_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.json"
            row = {"url": "https://www.pichau.com.br/ssd-kingston-1tb", "title": "SSD Kingston 1TB",
                   "seller_id": "Pichau", "price_cents": 38000, "currency": "BRL", "available": True,
                   "payment_terms": "PIX", "observed_at": datetime.now(timezone.utc).isoformat()}
            def write():
                path.write_text(json.dumps({"schema_version": 1, "store": "pichau", "offers": [row]}), encoding="utf-8")
            write()
            source = AuthorizedFeed("pichau", {"feed_path": str(path)})
            with self.assertRaises(SourceError):
                source.offers()
            source.options["authorization_reference"] = "Acordo do fornecedor de teste"
            self.assertEqual(len(source.search("ssd", 20)), 1)
            row["observed_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            write()
            with self.assertRaises(SourceError) as error:
                source.offers()
            self.assertEqual(error.exception.state, "stale_feed")


if __name__ == "__main__":
    unittest.main()
