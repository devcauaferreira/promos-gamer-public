from collectors.browser_source import LegacyBrowserSource


class KabumSource(LegacyBrowserSource):
    def __init__(self, db, browser):
        super().__init__(db, "kabum", browser)
