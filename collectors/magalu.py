"""APIs de seller não são usadas como API pública de comparação de preços."""
from collectors.feed import AuthorizedFeed


class MagaluSource(AuthorizedFeed):
    def __init__(self, options):
        super().__init__("magalu", options)
