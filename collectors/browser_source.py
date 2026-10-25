from dataclasses import replace
from datetime import datetime, timezone

from collectors.base import SourceError
from collectors.discovery import parse_links, search_url
from collectors.catalog import store_for_url
from collectors.web_product import collect
from services.browser_http import navigate
from services.http_client import JsonHttpClient


class LegacyBrowserSource:
    mode = "legacy_web"

    def __init__(self, db, store, browser):
        self.store, self.browser = store, browser
        self.client = JsonHttpClient(db, store, store + ":legacy_web")

    def status(self):
        return {**self.client.health(), "notice": "Integração web legada; não é API oficial nem comprova autorização da loja"}

    def search(self, category, limit):
        page = self.browser.new_page(locale="pt-BR")
        try:
            url = search_url(self.store, category)
            navigate(page, url, self.client, "category_search", 25000)
            if store_for_url(page.url) != self.store:
                raise SourceError("invalid_response", "Redirecionamento para outra loja")
            page.wait_for_timeout(2000)
            text = page.locator("body").inner_text().lower()
            if any(term in text for term in ("digite os caracteres", "verify you are human", "robot check", "confirme que você é humano")):
                self.client.fail("access_denied")
                raise SourceError("access_denied", "Verificação humana solicitada; consulta suspensa")
            entries = parse_links(page.content(), page.url, self.store, category, limit)
            if not entries:
                # Resultados podem aparecer após o HTML inicial no navegador do runner.
                page.wait_for_timeout(3000)
                entries = parse_links(page.content(), page.url, self.store, category, limit)
            self.client.fail("operational")
            return entries
        finally:
            page.close()

    def collect(self, entry):
        offer = replace(collect(entry, self.browser, self.client), source=self.mode,
                        observed_at=datetime.now(timezone.utc).isoformat())
        self.client.fail("operational")
        return offer
