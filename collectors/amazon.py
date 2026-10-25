"""Creators API depende de elegibilidade; sem acesso, aceita somente feed autorizado."""
from collectors.feed import AuthorizedFeed


class AmazonSource(AuthorizedFeed):
    def __init__(self, options):
        super().__init__("amazon", options)
