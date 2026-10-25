from urllib.parse import urlparse


def valid_affiliate_link(offer):
    """Validação estrutural; autorização deve vir da integração oficial."""
    try:
        url = urlparse(offer.affiliate_url)
        return bool(offer.affiliate_allowed and url.scheme == "https" and url.hostname
                    and not url.username and not url.password)
    except ValueError:
        return False
