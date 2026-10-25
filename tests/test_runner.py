import json
import os
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from database.models import connect
from services.price_history import record_price
from services.runner import cycle


class RunnerIntegration(unittest.TestCase):
    def test_authorized_feed_to_confirmed_dispatch_without_browser(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                now = datetime.now(timezone.utc)
                row = {"url": "https://www.pichau.com.br/ssd-kingston-1tb", "title": "SSD Kingston 1TB",
                       "seller_id": "Pichau", "shipped_by": "Pichau", "price_cents": 38000, "currency": "BRL", "available": True,
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
