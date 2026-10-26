"""Seleciona uma fonte por loja, sem fallback silencioso para scraping."""
from collectors.base import SourceError
from collectors.catalog import DOMAINS

DEFAULT_MODES = {"mercadolivre": "official_api", "kabum": "legacy_web",
                 "amazon": "authorized_feed", "magalu": "authorized_feed", "pichau": "authorized_feed"}


class LazyBrowser:
    def __init__(self, visible=False):
        self.visible, self.browser, self.manager = visible, None, None

    def new_page(self, **kwargs):
        if self.browser is None:
            from playwright.sync_api import sync_playwright
            self.manager = sync_playwright().start()
            self.browser = self.manager.chromium.launch(headless=not self.visible)
        return self.browser.new_page(**kwargs)

    def close(self):
        if self.browser:
            self.browser.close()
        if self.manager:
            self.manager.stop()


class DisabledSource:
    mode = "disabled"

    def __init__(self, store):
        self.store = store

    def status(self):
        return {"state": "disabled", "error": "Fonte desativada na configuração"}

    def search(self, category, limit):
        raise SourceError("disabled", "Fonte desativada")

    def collect(self, entry):
        raise SourceError("disabled", "Fonte desativada")


def build_sources(db, settings, browser):
    from collectors.amazon import AmazonSource
    from collectors.feed import AuthorizedFeed
    from collectors.kabum import KabumSource
    from collectors.magalu import MagaluSource
    from collectors.mercadolivre import MercadoLivreSource
    from collectors.pichau import PichauSource
    feeds = {"amazon": AmazonSource, "magalu": MagaluSource, "pichau": PichauSource}
    sources = {}
    for store in DOMAINS:
        options = settings.get("sources", {}).get(store, {})
        mode = options.get("mode", DEFAULT_MODES[store])
        if mode == "disabled":
            source = DisabledSource(store)
        elif mode == "official_api" and store == "mercadolivre":
            source = MercadoLivreSource(db, options)
        elif mode == "authorized_feed":
            source = feeds[store](options) if store in feeds else AuthorizedFeed(store, options)
        elif mode == 'public_catalog_review' and store == 'amazon':
            from collectors.amazon_public import AmazonPublicReview
            source = AmazonPublicReview(db, options)
        elif mode == "legacy_web" and store == "kabum":
            source = KabumSource(db, browser)
        else:
            raise ValueError(f"Modo de fonte não implementado para {store}: {mode}")
        sources[store] = source
    return sources


def source_report(sources):
    return [{"store": store, "mode": source.mode, **source.status()} for store, source in sources.items()]
