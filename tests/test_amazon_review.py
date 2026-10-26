import io
import json
import unittest
from contextlib import closing
from email.message import Message
from unittest.mock import Mock
from urllib.error import HTTPError

from collectors.amazon_public import AmazonPublicReview, parse_amazon_review
from collectors.base import SourceError
from database.models import connect


class AmazonReviewTests(unittest.TestCase):
    def entry(self):
        return {'store': 'amazon', 'id': 'amazon-B09VCJ171S',
                'url': 'https://www.amazon.com.br/dp/B09VCJ171S'}

    def html(self, asin='B09VCJ171S', seller='Amazon.com.br'):
        components = json.dumps({'1': {'minQuantity': 1, 'showPrice': True, 'suppressed': False,
                                      'price': {'currencyCode': 'BRL', 'wholeValue': '597', 'fractionalValue': '55'}}})
        return f'''<input id="ASIN" value="B09VCJ171S"><h1 id="productTitle">Processador AMD Ryzen 5 5500</h1>
        <div id="dynamic-aod-ingress-box"><span class="a-price">R$ 589,00</span></div>
        <div id="sims-productBundle_feature_div_0"><div data-components='{components}'>
        <div data-csa-c-item-id="amzn1.asin.{asin}" data-csa-c-pos="1">
        <span class="a-price">R$ 597,55</span>Em estoque Enviado de e vendido por {seller}.</div></div></div>
        <div class="recommendations"><span class="a-price">R$ 10,00</span></div>'''

    def test_exact_asin_quote_is_separate_from_buybox_and_never_eligible(self):
        offer = parse_amazon_review(self.html(), self.entry())
        self.assertEqual(offer.price_cents, 59755)
        self.assertEqual(offer.seller_id, 'Amazon.com.br')
        self.assertEqual(offer.price_basis, 'amazon_bundle_unit_quote')
        self.assertFalse(offer.available)
        self.assertEqual(offer.availability_evidence, 'review_bundle_only')

    def test_other_asin_or_partner_seller_cannot_supply_this_quote(self):
        for html in (self.html(asin='B000000000'), self.html(seller='Parceiro'),
                     self.html().replace('Em estoque', 'Indisponível')):
            with self.assertRaises(SourceError):
                parse_amazon_review(html, self.entry())

    def test_403_suspends_source_across_instances_without_repeated_request(self):
        with closing(connect(':memory:')) as db:
            opener = Mock()
            opener.open.side_effect = HTTPError(self.entry()['url'], 403, 'denied', Message(), io.BytesIO())
            source = AmazonPublicReview(db, {}, opener=opener)
            with self.assertRaises(SourceError):
                source.collect(self.entry())
            restarted = AmazonPublicReview(db, {}, opener=opener)
            self.assertEqual(restarted.status()['state'], 'access_denied')
            with self.assertRaises(SourceError):
                restarted.collect(self.entry())
            opener.open.assert_called_once()

    def test_503_defers_source_without_immediate_retry(self):
        with closing(connect(':memory:')) as db:
            opener = Mock()
            headers = Message(); headers['Retry-After'] = '1200'
            opener.open.side_effect = HTTPError(self.entry()['url'], 503, 'unavailable', headers, io.BytesIO())
            source = AmazonPublicReview(db, {}, opener=opener)
            with self.assertRaises(SourceError):
                source.collect(self.entry())
            self.assertEqual(source.status()['state'], 'temporarily_unavailable')
            with self.assertRaises(SourceError):
                source.collect(self.entry())
            opener.open.assert_called_once()
