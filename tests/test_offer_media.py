import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import patch

from PIL import Image, ImageDraw

from collectors.web_product import parse_product
from database.models import Offer, connect
from config import Config
from publishers.image_card import format_image, validate_settings, _product_palette
from publishers.whatsapp import product_image, publish
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
        self.assertIn('🔥 *Por R$ 529,62*', message)
        self.assertIn('33,7% abaixo da média observada', message)
        self.assertIn('Observado em 12 dias de coleta', message)
        self.assertIn('🏬 Kabum • Vendedor: KaBuM!', message)
        self.assertIn('💳 À vista no PIX', message)
        self.assertIn('🛒 *COMPRE AQUI*', message)
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

    def test_unconfirmed_marketplace_catalog_message_warns_and_hides_unknown_payment(self):
        offer = Offer('mercadolivre', 'ml-item', 'Processador Ryzen 5', '42', 38000,
                      None, 'Preço do anúncio no catálogo; confira as condições de pagamento na loja',
                      False, 'https://www.mercadolivre.com.br/p/MLB19444510',
                      source='official_catalog', official_store_id=1,
                      availability_evidence='unknown')
        message = build_message(offer, Decision('approved', 50000, 24.0, ()))
        self.assertIn('⚠️ *ESTOQUE NÃO CONFIRMADO*', message)
        self.assertIn('Confirme a disponibilidade e as condições de pagamento no Mercado Livre', message)
        self.assertNotIn('💳', message)
        self.assertNotIn('Preço do anúncio no catálogo', message)

    def test_unconfirmed_amazon_feed_message_warns_and_hides_payment(self):
        offer = Offer('amazon', 'amazon-item', 'Processador Ryzen 5', 'Amazon.com.br', 38000,
                      None, 'À vista no PIX', False, 'https://www.amazon.com.br/dp/B09VCJ171S',
                      source='authorized_feed', shipped_by='Amazon.com.br',
                      availability_evidence='unknown')
        message = build_message(offer, Decision('approved', 50000, 24.0, ()))
        self.assertIn('⚠️ *ESTOQUE NÃO CONFIRMADO*', message)
        self.assertIn('Confirme a disponibilidade e as condições de pagamento na Amazon', message)
        self.assertNotIn('💳 À vista no PIX', message)

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

    @patch('publishers.whatsapp.runner_bridge', return_value=True)
    @patch('publishers.whatsapp.bridge_token', return_value='x' * 32)
    @patch('publishers.whatsapp.product_image', return_value=None)
    @patch('urllib.request.build_opener')
    def test_failed_background_replacement_does_not_send_unprocessed_photo(
            self, opener, photo, token, runner):
        with self.assertRaisesRegex(ValueError, 'imagem gamer'):
            publish('Oferta', 'test@g.us',
                    image_url='https://images.kabum.com.br/produtos/fotos/320799/photo.jpg')
        opener.assert_not_called()

    @patch('publishers.image_card.remove_background')
    def test_product_photo_background_is_replaced_with_gamer_scene(self, remove_background):
        source = BytesIO()
        original = Image.new('RGB', (100, 50), '#0000ff')
        ImageDraw.Draw(original).rectangle((25, 10, 75, 40), fill='#ff0000')
        original.save(source, format='PNG')

        def segment(image):
            cutout = image.copy()
            mask = Image.new('L', image.size, 0)
            ImageDraw.Draw(mask).rectangle((25, 10, 75, 40), fill=255)
            cutout.putalpha(mask)
            return cutout

        remove_background.side_effect = segment

        result = Image.open(BytesIO(format_image(
            source.getvalue(),
            {'background_color': '#123456', 'accent_color': '#00aa88', 'badge_text': 'MEU BOT'},
        )))

        self.assertEqual(result.format, 'JPEG')
        self.assertEqual(result.size, (1440, 1440))
        replaced_background = result.getpixel((200, 500))
        self.assertNotEqual(replaced_background, (0, 0, 255))
        red = result.getpixel((720, 632))
        self.assertGreater(red[0], 240)
        self.assertLess(red[1], 15)
        self.assertLess(red[2], 15)
        remove_background.assert_called_once()

    def test_image_card_settings_reject_invalid_customization(self):
        with self.assertRaisesRegex(ValueError, 'background_color'):
            validate_settings({'background_color': 'blue'})
        with self.assertRaisesRegex(ValueError, 'badge_text'):
            validate_settings({'badge_text': 'x' * 31})

    def test_auto_palette_follows_the_product_main_color(self):
        red_product = Image.new('RGBA', (80, 80), (240, 24, 16, 255))
        green_product = Image.new('RGBA', (80, 80), (20, 220, 40, 255))
        settings = validate_settings()

        red_palette = _product_palette(red_product, settings)
        green_palette = _product_palette(green_product, settings)

        self.assertNotEqual(red_palette['glow_color'], green_palette['glow_color'])
        self.assertNotEqual(red_palette['accent_color'], green_palette['accent_color'])
        self.assertNotEqual(red_palette['background_color'], green_palette['background_color'])

    def test_auto_palette_can_be_disabled_for_fixed_brand_colors(self):
        palette = _product_palette(
            Image.new('RGBA', (20, 20), (240, 24, 16, 255)),
            validate_settings({'auto_colors': False}),
        )

        self.assertEqual(palette['background_color'], '#111827')
        self.assertEqual(palette['accent_color'], '#22C55E')
        self.assertEqual(palette['glow_color'], '#00C8FF')

    def test_kabum_photo_must_match_product_id(self):
        html = '''<meta property="og:image" content="https://images.kabum.com.br/produtos/fotos/999/photo.jpg">
        <script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"product":
        {"id":320799,"title":"Processador Ryzen 5 5500","prices":{"price":500},
        "sellerName":"KaBuM!","available":true}}}}</script>'''
        entry = {'store':'kabum','id':'cpu','url':'https://www.kabum.com.br/produto/320799/cpu'}
        self.assertEqual(parse_product(html, entry).image_url, '')
        self.assertEqual(parse_product(html.replace('/999/', '/320799/'), entry).image_url,
                         'https://images.kabum.com.br/produtos/fotos/320799/photo.jpg')

    def test_kabum_photo_prefers_preloaded_full_resolution_image(self):
        image_prefix = 'https://images.kabum.com.br/produtos/fotos/320799/'
        html = (
            '<link rel="preload" as="image" href="' + image_prefix + 'product_gg.jpg">'
            '<meta property="og:image" content="' + image_prefix + 'product_m.jpg">'
            '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"product":'
            '{"id":320799,"title":"Processador Ryzen 5 5500","prices":{"price":500},'
            '"sellerName":"KaBuM!","available":true}}}}</script>'
        )
        entry = {'store':'kabum','id':'cpu','url':'https://www.kabum.com.br/produto/320799/cpu'}
        self.assertEqual(parse_product(html, entry).image_url, f'{image_prefix}product_gg.jpg')


if __name__ == '__main__':
    unittest.main()
