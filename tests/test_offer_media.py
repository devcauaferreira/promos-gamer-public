import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from collectors.web_product import parse_product
from database.models import Offer, connect
from config import Config
from publishers.whatsapp import product_image
from services.discount_filter import Decision, evaluate
from services.message_builder import build_message
from services.price_history import record_price


class OfferMediaTests(unittest.TestCase):
    def test_message_uses_default_30_day_average_instead_of_struck_price(self):
        offer = Offer('kabum', 'cpu', 'Processador Ryzen 5 5500', 'KaBuM!', 52962,
                      None, 'À vista no PIX', True, 'https://www.kabum.com.br/produto/320799')
        # Quatro argumentos continuam válidos após adicionar a janela à decisão.
        decision = Decision('approved', 79900, 33.7, (), history_samples=12)
        message = build_message(offer, decision)
        self.assertEqual(decision.history_days, 30)
        self.assertIn('Média dos últimos 30 dias: R$ 799,00', message)
        self.assertIn('💚 *R$ 529,62*', message)
        self.assertIn('33,7% abaixo da média', message)
        self.assertIn('Base: 12 dia(s) observado(s)', message)
        self.assertIn('🏬 Kabum • Vendedor: KaBuM!', message)
        self.assertIn('💳 À vista no PIX', message)
        self.assertIn('🛒 *COMPRAR AGORA*', message)
        self.assertIn('— *Promos Gamer*', message)
        self.assertNotIn('De: ', message)

    def test_message_reuses_existing_category_classifier_and_generic_heading(self):
        examples = (
            ('Placa de vídeo GeForce RTX 4070', 'PLACAS DE VÍDEO'),
            ('Kit upgrade Ryzen 5 com placa mãe', 'KITS UPGRADE'),
            ('Processador Ryzen 5 5500', 'PROCESSADORES'),
            ('Memória RAM DDR5 16GB', 'MEMÓRIA RAM'),
            ('Mouse gamer sem fio', 'OFERTA GAMER'),
            ('Notebook gamer', 'OFERTA GAMER'),
        )
        for title, heading in examples:
            with self.subTest(title=title):
                offer = Offer('kabum', 'item', title, '', 10000, None, '', True, '')
                message = build_message(offer, Decision('approved', None, None, ()))
                self.assertIn(f'PROMOS GAMER • {heading}', message)

    def test_message_omits_missing_optional_fields(self):
        offer = Offer('', 'item', 'Produto sem categoria', '', 10000, None, '', True, '')
        decision = Decision('approved', None, None, ())
        message = build_message(offer, decision)
        self.assertNotIn('HISTÓRICO DE PREÇOS', message)
        self.assertNotIn('Média dos últimos', message)
        self.assertNotIn('Vendedor:', message)
        self.assertNotIn('Entregue por:', message)
        self.assertNotIn('💳', message)
        self.assertNotIn('COMPRAR AGORA', message)
        self.assertNotIn('None', message)
        self.assertIn('Frete não incluído.', message)
        self.assertIn('— *Promos Gamer*', message)

    def test_message_window_matches_the_window_used_to_evaluate_the_offer(self):
        offer = Offer('kabum', 'cpu', 'Processador Ryzen 5 5500', 'KaBuM!', 52962,
                      None, 'À vista no PIX', True, 'https://www.kabum.com.br/produto/320799',
                      shipped_by='KaBuM!')
        now = datetime.now(timezone.utc)
        with closing(connect(':memory:')) as db:
            record_price(db, 'kabum', 'cpu', 79900, now - timedelta(days=1))
            record_price(db, 'kabum', 'cpu', 100000, now - timedelta(days=10))
            for days, average in ((7, 79900), (30, 89950)):
                with self.subTest(days=days):
                    decision = evaluate(db, offer, Config(history_days=days), now)
                    message = build_message(offer, decision)
                    self.assertEqual(decision.history_days, days)
                    self.assertEqual(decision.average_cents, average)
                    self.assertIn(f'Média dos últimos {days} dias:', message)

    @patch('urllib.request.build_opener')
    def test_photo_rejects_untrusted_url_without_network(self, opener):
        self.assertIsNone(product_image('https://evil.example/steal'))
        self.assertIsNone(product_image('http://images.kabum.com.br/produtos/fotos/1/a.jpg'))
        opener.assert_not_called()

    def test_kabum_photo_must_match_product_id(self):
        html = '''<meta property="og:image" content="https://images.kabum.com.br/produtos/fotos/999/photo.jpg">
        <script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"product":
        {"id":320799,"title":"Processador Ryzen 5 5500","prices":{"price":500},
        "sellerName":"KaBuM!","available":true}}}}</script>'''
        entry = {'store':'kabum','id':'cpu','url':'https://www.kabum.com.br/produto/320799/cpu'}
        self.assertEqual(parse_product(html, entry).image_url, '')
        self.assertEqual(parse_product(html.replace('/999/', '/320799/'), entry).image_url,
                         'https://images.kabum.com.br/produtos/fotos/320799/photo.jpg')


if __name__ == '__main__':
    unittest.main()
