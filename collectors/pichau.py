from collectors.feed import AuthorizedFeed


class PichauSource(AuthorizedFeed):
    def __init__(self, options):
        super().__init__("pichau", options)
