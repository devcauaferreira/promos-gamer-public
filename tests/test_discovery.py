import unittest
from contextlib import closing
from datetime import datetime, timezone
from unittest.mock import Mock

from collectors.catalog import canonical_product
from collectors.discovery import discover, parse_links
from collectors.base import SourceError
from database.models import connect
from services.niche import category_for


class DiscoveryTests(unittest.TestCase):
    def test_categories_and_unrelated_products(self):
        for title, category in [
            ("Processador AMD Ryzen 5 5500", "processador"),
            ("Placa Mãe MSI B550M", "placa_mae"),
            ("Memória Kingston Fury DDR5 16GB", "memoria_ram"),
            ("SSD Kingston NV3 1TB NVMe", "ssd"),
            ("Fonte Corsair RM650 650W 80 Plus", "fonte"),
            ("Fonte ATX 650W para computador gamer", "fonte"),
            ("Placa de Vídeo GeForce RTX 4060 8GB", "placa_video"),
            ("Placa Vídeo Radeon RX 7600 8GB", "placa_video"),
            ("Kit Upgrade AMD Ryzen 5 5500 Placa Mãe MSI A520M", "kit_upgrade"),
            ("Kit Processador Ryzen 5 5500 + Placa Mãe A520M", "kit_upgrade"),
            ("Memória RAM DDR 5 16GB para notebook", "memoria_ram"),
            ("Cabo para fonte 650W", None),
            ("PC Gamer Ryzen 5 SSD 1TB", None),
            ("Fonte carregador notebook 65W", None),
            ("Case para SSD NVMe", None),
            ("Suporte para placa de vídeo RTX 4060", None),
            ("PC Gamer com kit upgrade Ryzen 5", None),
        ]:
            with self.subTest(title=title):
                self.assertEqual(category_for(title), category)

    def test_identifiers_drop_tracking_keep_seller(self):
        self.assertEqual(canonical_product("https://www.kabum.com.br/produto/320799/cpu?utm_source=x#foo"),
                         ("kabum-320799", "https://www.kabum.com.br/produto/320799/cpu"))
        product_id, url = canonical_product("https://www.amazon.com.br/title/dp/B09VCJ171S?smid=SELLER&tag=tag")
        self.assertEqual(product_id, "amazon-B09VCJ171S-SELLER")
        self.assertIn("smid=SELLER", url)
        self.assertNotIn("tag=", url)
        product_id, url = canonical_product("https://www.mercadolivre.com.br/cpu/up/MLBU123?pdp_filters=item_id%3AMLB5391978169#tracking")
        self.assertEqual(product_id, "ml-MLB5391978169")
        self.assertIn("MLB5391978169", url)
        for url in ("https://www.kabum.com.br/busca/ssd", "https://www.pichau.com.br/search?q=ssd"):
            with self.assertRaises(ValueError):
                canonical_product(url)

    def test_discovery_rejects_offsite_accessory_and_duplicate(self):
        html = '''
        <a href="https://evil.example/produto/1">SSD falso 1TB</a>
        <a href="/produto/1/ssd?utm_source=x">SSD Kingston 1TB</a>
        <a href="/produto/1/ssd?utm_source=y">SSD Kingston 1TB</a>
        <a href="/produto/2/cabo">Cabo para SSD</a>
        <a href="/produto/3/ram">Memoria RAM DDR4 8GB</a>
        <a href="/produto/4/ssd">SSD Samsung 2TB</a>
        '''
        rows = parse_links(html, "https://www.kabum.com.br/busca/ssd", "kabum", "ssd", 20)
        self.assertEqual([row["id"] for row in rows], ["kabum-1", "kabum-4"])

    def test_http_block_stops_other_categories_and_is_cached(self):
        browser = Mock()
        source = Mock()
        source.mode = "official_api"
        source.status.return_value = {"state": "ready_to_validate"}
        source.search.side_effect = SourceError("access_denied", "HTTP 403")
        settings = {"discovery": {"stores": ["mercadolivre"], "categories": ["ssd", "fonte"]}}
        with closing(connect(":memory:")) as db:
            rows = discover(db, browser, settings, sources={"mercadolivre": source})
            self.assertEqual(source.search.call_count, 1)
            browser.new_page.assert_not_called()
            self.assertEqual([row["status"] for row in rows], ["access_denied", "skipped"])
            cached = discover(db, browser, settings, sources={"mercadolivre": source})
            self.assertEqual(source.search.call_count, 1)
            self.assertTrue(all(row["cached"] for row in cached))
            self.assertIn("HTTP 403", cached[0]["error"])

    def test_empty_legacy_search_is_retried_next_cycle(self):
        source = Mock()
        source.mode = "legacy_web"
        source.status.return_value = {"state": "ready_to_validate"}
        entry = {"id": "kabum-1", "store": "kabum", "url": "https://www.kabum.com.br/produto/1",
                 "category": "kit_upgrade", "enabled": True}
        source.search.side_effect = [[], [entry]]
        settings = {"discovery": {"stores": ["kabum"], "categories": ["kit_upgrade"]}}
        with closing(connect(":memory:")) as db:
            self.assertEqual(discover(db, Mock(), settings, sources={"kabum": source})[0]["found"], 0)
            self.assertEqual(discover(db, Mock(), settings, sources={"kabum": source})[0]["found"], 1)
            self.assertEqual(source.search.call_count, 2)


if __name__ == "__main__":
    unittest.main()
