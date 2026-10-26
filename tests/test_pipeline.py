import json
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from collectors.catalog import store_for_url
from collectors.web_product import parse_product, cents
from config import Config
from database.models import connect
from services.discount_filter import evaluate, mark_published
from services.price_history import record_price


class PriceRules(unittest.TestCase):
    def offer(self, **changes):
        entry = {"id": "cpu", "store": "kabum", "url": "https://www.kabum.com.br/produto/1",
                 "payment_terms": "PIX"}
        product = {"@type": "Product", "name": "Ryzen", "offers": {
            "@type": "Offer", "price": "360.00", "priceCurrency": "BRL",
            "availability": "https://schema.org/InStock", "seller": {"name": "KaBuM!"}}}
        product["offers"].update(changes)
        return parse_product('<div><span>Vendido e entregue por:</span><b>KaBuM!</b></div>'
                             + '<script type="application/ld+json">' + json.dumps(product) + '</script>', entry)

    def test_real_discount_without_affiliate_or_shipping(self):
        now = datetime.now(timezone.utc)
        config = Config(trusted_sellers=frozenset({("kabum", "KaBuM!")}))
        offer = self.offer()
        with closing(connect(":memory:")) as db:
            self.assertEqual(evaluate(db, offer, config, now).status, "pending_review")
            for days in (1, 2, 3):
                record_price(db, "kabum", "cpu", 49000, now - timedelta(days=days))
            decision = evaluate(db, offer, config, now, "whatsapp:group")
            self.assertEqual(decision.status, "approved")
            self.assertAlmostEqual(decision.discount_percent, 26.53061224)
            record_price(db, "kabum", "cpu", 36000, now)
            self.assertEqual(evaluate(db, offer, config, now).average_cents, 49000)
            mark_published(db, offer, "whatsapp:group", now)
            self.assertEqual(evaluate(db, offer, config, now, "whatsapp:group").status, "pending_review")
            self.assertEqual(evaluate(db, replace(offer, available=False), config, now).status, "pending_review")

    def test_one_prior_day_allows_real_drop_but_not_same_day(self):
        now = datetime.now(timezone.utc)
        config = Config(minimum_history_days=1)
        offer = self.offer()
        with closing(connect(":memory:")) as db:
            record_price(db, "kabum", "cpu", 49000, now)
            self.assertEqual(evaluate(db, offer, config, now).status, "pending_review")
            record_price(db, "kabum", "cpu", 49000, now - timedelta(days=1))
            decision = evaluate(db, offer, config, now)
            self.assertEqual(decision.status, "approved")
            self.assertAlmostEqual(decision.discount_percent, 26.53061224)

    def test_monthly_rule_accepts_exactly_25_percent_and_uses_only_prior_30_days(self):
        now = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
        with closing(connect(':memory:')) as db:
            for days in (20, 30):
                record_price(db, 'kabum', 'cpu', 50000, now - timedelta(days=days))
            record_price(db, 'kabum', 'cpu', 90000, now - timedelta(days=31))
            record_price(db, 'kabum', 'cpu', 100000, now)
            config = Config()
            decision = evaluate(db, self.offer(price='375.00'), config, now)
            self.assertEqual(decision.average_cents, 50000)
            self.assertEqual(decision.discount_percent, 25)
            self.assertEqual(decision.status, 'approved')
            below_threshold = evaluate(db, self.offer(price='375.01'), config, now)
            self.assertEqual(below_threshold.status, 'pending_review')
            self.assertIn('Queda abaixo do mínimo exigido', below_threshold.reasons)

    def test_weekly_window_excludes_prices_older_than_seven_days(self):
        now = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
        offer = self.offer()
        with closing(connect(":memory:")) as db:
            record_price(db, "kabum", "cpu", 49000, now - timedelta(days=8))
            record_price(db, "kabum", "cpu", 49000, now - timedelta(days=7))
            decision = evaluate(db, offer, Config(history_days=7), now)
            self.assertEqual(decision.status, "approved")
            self.assertEqual(decision.average_cents, 49000)
            db.execute("DELETE FROM prices WHERE day=?", ((now - timedelta(days=7)).date().isoformat(),))
            self.assertEqual(evaluate(db, offer, Config(history_days=7), now).status, "pending_review")

    def test_parser_rejects_wrong_currency(self):
        with self.assertRaises(ValueError):
            self.offer(priceCurrency="USD")

    def test_marketplace_seller_is_not_approved_by_store_alone(self):
        now = datetime.now(timezone.utc)
        config = Config(trusted_sellers=frozenset({("kabum", "KaBuM!")}))
        offer = self.offer(seller={"name": "Vendedor desconhecido"})
        with closing(connect(":memory:")) as db:
            for days in (1, 2, 3):
                record_price(db, "kabum", "cpu", 49000, now - timedelta(days=days))
            decision = evaluate(db, offer, config, now)
            self.assertIn("Produto não vendido pela própria loja", decision.reasons)
            self.assertEqual(decision.status, "pending_review")

    def test_parser_rejects_aggregate_price(self):
        with self.assertRaises(ValueError):
            self.offer(price=None)

    def test_money(self):
        self.assertEqual(cents("R$ 1.234,56"), 123456)
        self.assertEqual(cents("380.00"), 38000)
        for value in ("NaN", "Infinity", "-1", "0"):
            with self.assertRaises(ValueError):
                cents(value)

    def test_domains(self):
        for domain in ("amazon.com.br", "mercadolivre.com.br", "magazineluiza.com.br", "kabum.com.br", "pichau.com.br"):
            store_for_url("https://www." + domain + "/produto")
        with self.assertRaises(ValueError):
            store_for_url("https://kabum.com.br.example.org/produto")

    def test_kabum_current_product_not_recommendation(self):
        entry = {"id": "kabum-1003965", "store": "kabum",
                 "url": "https://www.kabum.com.br/produto/1003965/kit"}
        data = {"props": {"pageProps": {"product": {
            "id": 1003965, "title": "Kit Ryzen", "sellerName": "KaBuM!",
            "available": True, "prices": {"price": 999.99, "priceWithDiscount": 979.99, "oldPrice": 1500}}}}}
        html = '<p>À vista no PIX</p><script id="__NEXT_DATA__">' + json.dumps(data) + '</script>'
        offer = parse_product(html, entry)
        self.assertEqual(offer.price_cents, 97999)
        self.assertEqual(offer.seller_id, "KaBuM!")
        self.assertEqual(offer.payment_terms, "À vista no PIX")
        self.assertTrue(offer.available)
        with self.assertRaises(ValueError):
            parse_product(html, dict(entry, url="https://www.kabum.com.br/produto/2/outro"))


if __name__ == "__main__":
    unittest.main()
