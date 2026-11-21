import json
import os
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock, patch

from config import Config
from database.models import Offer, connect
from services.price_history import record_price
from services.runner import cycle


class RunnerIntegration(unittest.TestCase):
    def test_amazon_unknown_stock_authorized_feed_sends_with_warning(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                now = datetime.now(timezone.utc)
                entry = {"store": "amazon", "id": "amazon-B09VCJ171S",
                         "url": "https://www.amazon.com.br/dp/B09VCJ171S"}
                row = {"url": entry["url"], "title": "Processador AMD Ryzen 5 5500",
                       "seller_id": "Amazon.com.br", "shipped_by": "Amazon.com.br",
                       "price_cents": 37000, "currency": "BRL", "available": False,
                       "availability_evidence": "unknown", "payment_terms": "À vista no PIX",
                       "observed_at": now.isoformat()}
                Path("products.json").write_text(json.dumps([entry]), encoding="utf-8")
                Path("feed.json").write_text(json.dumps({
                    "schema_version": 1, "store": "amazon", "offers": [row]}), encoding="utf-8")
                settings = {"database_path": "prices.sqlite3", "minimum_discount_percent": 25,
                            "whatsapp_group_id": "test@g.us",
                            "sources": {store: {"mode": "disabled"} for store in
                                        ("amazon", "mercadolivre", "magalu", "kabum", "pichau")},
                            "discovery": {"enabled": False}}
                settings["sources"]["amazon"] = {
                    "mode": "authorized_feed", "feed_path": "feed.json",
                    "authorization_reference": "Fornecedor autorizado"}
                Path("settings.json").write_text(json.dumps(settings), encoding="utf-8")
                initial = cycle(send=True)
                self.assertEqual(initial[0]["decision"]["status"], "pending_review")
                self.assertFalse(initial[0]["offer"]["available"])
                self.assertEqual(initial[0]["offer"]["availability_evidence"], "unknown")
                with closing(connect("prices.sqlite3")) as db:
                    record_price(db, "amazon", initial[0]["offer"]["product_id"],
                                 50000, now - timedelta(days=1))
                with patch("services.runner.publish", return_value="confirmed-id") as publish:
                    delivered = cycle(send=True)
                    self.assertEqual(delivered[0]["decision"]["status"], "approved")
                    self.assertEqual(delivered[0]["send_status"], "sent")
                    self.assertIn("⚠️ *ESTOQUE NÃO CONFIRMADO*", delivered[0]["message"])
                    self.assertIn("na Amazon antes de comprar", delivered[0]["message"])
                    self.assertNotIn("💳 À vista no PIX", delivered[0]["message"])
                    publish.assert_called_once()
            finally:
                os.chdir(previous)

    def test_amazon_revalidation_rejects_changed_availability_evidence(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                entry = {"store": "amazon", "id": "amazon-B09VCJ171S",
                         "url": "https://www.amazon.com.br/dp/B09VCJ171S"}
                Path("products.json").write_text(json.dumps([entry]), encoding="utf-8")
                offer = Offer("amazon", entry["id"], "Processador AMD Ryzen 5 5500",
                              "Amazon.com.br", 37000, None, "PIX", False, entry["url"],
                              source="authorized_feed", price_basis="feed_price",
                              shipped_by="Amazon.com.br", availability_evidence="unknown")
                basis = "Amazon.com.br|PIX|product-only|authorized_feed|feed_price"
                product_id = f"{entry['id']}:{sha256(basis.encode()).hexdigest()[:12]}"
                with closing(connect("prices.sqlite3")) as db:
                    record_price(db, "amazon", product_id, 50000,
                                 datetime.now(timezone.utc) - timedelta(days=1))
                source = Mock()
                source.collect.side_effect = [
                    offer, Offer("amazon", offer.product_id, offer.title, offer.seller_id,
                                 offer.price_cents, offer.shipping_cents, offer.payment_terms,
                                 offer.available, offer.affiliate_url, source="authorized_feed",
                                 price_basis="feed_price", shipped_by="Amazon.com.br",
                                 availability_evidence="unavailable")]
                config = Config(database_path=Path("prices.sqlite3"))
                settings = {"whatsapp_group_id": "test@g.us",
                            "discovery": {"enabled": False}}
                with patch("services.runner.load_settings", return_value=(config, settings)), \
                     patch("services.runner.build_sources", return_value={"amazon": source}), \
                     patch("services.runner.source_report", return_value=[]), \
                     patch("services.runner.publish") as publish:
                    result = cycle(send=True)
                self.assertEqual(result[0]["send_status"], "skipped: anúncio mudou durante a execução")
                publish.assert_not_called()
            finally:
                os.chdir(previous)

    def test_authorized_feed_to_confirmed_dispatch_without_browser(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                now = datetime.now(timezone.utc)
                row = {"url": "https://www.pichau.com.br/ssd-kingston-1tb", "title": "SSD Kingston 1TB",
                       "seller_id": "Pichau", "shipped_by": "Pichau", "price_cents": 36000, "currency": "BRL", "available": True,
                       "payment_terms": "PIX", "observed_at": now.isoformat()}
                Path("feed.json").write_text(json.dumps({"schema_version": 1, "store": "pichau", "offers": [row]}), encoding="utf-8")
                settings = {"database_path": "prices.sqlite3", "whatsapp_group_id": "test@g.us",
                            "trusted_sellers": [["pichau", "Pichau"]],
                            "sources": {store: {"mode": "disabled"} for store in ("amazon", "mercadolivre", "magalu", "kabum")},
                            "discovery": {"stores": ["pichau"], "categories": ["ssd"]}}
                settings["sources"]["pichau"] = {"mode": "authorized_feed", "feed_path": "feed.json", "authorization_reference": "Teste autorizado"}
                Path("settings.json").write_text(json.dumps(settings), encoding="utf-8")
                with patch("collectors.registry.LazyBrowser.new_page") as browser, patch("services.runner.publish", return_value="confirmed-id") as publish:
                    initial = cycle(send=True)
                    self.assertEqual(initial[0]["decision"]["status"], "pending_review")
                    publish.assert_not_called()
                    offer = initial[0]["offer"]
                    with closing(connect("prices.sqlite3")) as db:
                        for days in (1, 2, 3):
                            record_price(db, "pichau", offer["product_id"], 49000, now - timedelta(days=days))
                    approved = cycle(send=True)
                    self.assertEqual(approved[0]["send_status"], "sent")
                    self.assertEqual(publish.call_count, 1)
                    repeated = cycle(send=True)
                    self.assertEqual(repeated[0]["decision"]["status"], "pending_review")
                    self.assertEqual(publish.call_count, 1)
                    browser.assert_not_called()
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
