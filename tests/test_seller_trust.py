import unittest
from dataclasses import replace
from contextlib import closing
from datetime import datetime, timedelta, timezone

from database.models import Offer, connect
from config import Config
from services.price_history import record_price
from services.discount_filter import evaluate
from services.seller_trust import seller_rejection
from collectors.web_product import kabum_shipped_by
from bs4 import BeautifulSoup


class SellerTrustTests(unittest.TestCase):
    def offer(self, store="amazon", **kwargs):
        seller = "42" if store == "mercadolivre" else "Amazon.com.br"
        return Offer(store, "cpu", "Processador Ryzen 5 5500", seller, 36000, None, "PIX", True,
                     "https://example.com/product", **kwargs)

    def test_amazon_requires_sold_and_shipped_by_amazon(self):
        offer = self.offer(shipped_by="Amazon.com.br")
        self.assertIsNone(seller_rejection(offer))
        self.assertIsNotNone(seller_rejection(replace(offer, seller_id="Parceiro")))
        self.assertIsNotNone(seller_rejection(replace(offer, shipped_by="Parceiro")))
        self.assertIsNotNone(seller_rejection(replace(offer, shipped_by="")))
        self.assertIsNotNone(seller_rejection(replace(offer, seller_id="Amazon Loja Oficial XYZ")))

    def test_official_marketplace_store_needs_no_manual_seller_approval(self):
        offer = self.offer("mercadolivre", official_store_id=80562, source="official_catalog")
        now = datetime.now(timezone.utc)
        with closing(connect(":memory:")) as db:
            for days in (1, 2, 3):
                record_price(db, offer.store, offer.product_id, 49000, now - timedelta(days=days))
            self.assertEqual(evaluate(db, offer, Config(), now).status, "approved")
            for invalid in (None, 0, -1, True, "80562"):
                with self.subTest(invalid=invalid):
                    self.assertEqual(evaluate(db, replace(offer, official_store_id=invalid), Config(), now).status, "pending_review")
            self.assertIsNotNone(seller_rejection(replace(offer, source="legacy_web")))

    def test_allowlist_does_not_override_direct_store_rule(self):
        offer = replace(self.offer(shipped_by="Amazon.com.br"), seller_id="Parceiro")
        self.assertIsNotNone(seller_rejection(offer, {("amazon", "Parceiro")}))

    def test_all_direct_stores_accept_only_own_sale_and_delivery(self):
        for store, name in (("amazon", "Amazon.com.br"), ("kabum", "KaBuM!"),
                            ("magalu", "Magalu"), ("pichau", "Pichau")):
            with self.subTest(store=store):
                offer = replace(self.offer(), store=store, seller_id=name, shipped_by=name)
                self.assertIsNone(seller_rejection(offer))
                self.assertIsNotNone(seller_rejection(replace(offer, seller_id="Parceiro")))
                self.assertIsNotNone(seller_rejection(replace(offer, shipped_by="")))

    def test_kabum_delivery_label_must_match_current_seller(self):
        html = '<div><span>Vendido e entregue por:</span><b>KaBuM!</b></div>'
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(kabum_shipped_by(soup, "KaBuM!"), "KaBuM!")
        self.assertEqual(kabum_shipped_by(soup, "Parceiro"), "")
        self.assertEqual(kabum_shipped_by(BeautifulSoup('', "html.parser"), "KaBuM!"), "")
        self.assertEqual(kabum_shipped_by(BeautifulSoup(html + html, "html.parser"), "KaBuM!"), "")


if __name__ == "__main__":
    unittest.main()
