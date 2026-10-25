"""Identificação das cinco lojas e validação dos links cadastrados."""
from hashlib import sha256
from urllib.parse import urlparse
from urllib.parse import parse_qs, urlencode, urlunparse
import re

DOMAINS = {
    "amazon": ("amazon.com.br",),
    "mercadolivre": ("mercadolivre.com.br",),
    "magalu": ("magazineluiza.com.br",),
    "kabum": ("kabum.com.br",),
    "pichau": ("pichau.com.br",),
}


def store_for_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Use um link HTTPS direto do produto na loja")
    for store, domains in DOMAINS.items():
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return store
    raise ValueError("Loja não suportada; use Amazon, Mercado Livre, Magalu, KaBuM ou Pichau")


def product_key(url):
    try:
        return canonical_product(url)[0]
    except ValueError:
        return sha256(url.encode()).hexdigest()[:24]


def canonical_product(url):
    store = store_for_url(url)
    parsed = urlparse(url)
    path = parsed.path
    query = parse_qs(parsed.query)
    kept = {}
    key = None
    if store == "kabum":
        match = re.search(r"/produto/(\d+)(?:/|$)", path)
        if match:
            key = "kabum-" + match[1]
    elif store == "amazon":
        match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:/|$)", path, re.I)
        if match:
            key = "amazon-" + match[1].upper()
            path = "/dp/" + match[1].upper()
            for parameter in ("smid", "m"):
                if query.get(parameter):
                    kept[parameter] = query[parameter][0]
                    key += "-" + query[parameter][0]
    elif store == "mercadolivre":
        match = re.search(r"MLB-?(\d+)", path)
        selected = re.search(r"MLB(\d+)", " ".join(query.get("pdp_filters", []) + query.get("wid", [])))
        if selected or match:
            key = "ml-MLB" + (selected or match)[1]
            if selected:
                kept["pdp_filters"] = "item_id:MLB" + selected[1]
    elif store == "magalu":
        match = re.search(r"/p/([a-z0-9]+)(?:/|$)", path, re.I)
        if match:
            seller = query.get("seller_id", [""])[0]
            key = "magalu-" + match[1] + ("-" + seller if seller else "")
            if seller:
                kept["seller_id"] = seller
    elif store == "pichau":
        # Páginas de produto usam slug com palavras e números; categorias/buscas não entram.
        slug = path.strip("/")
        if "/" not in slug and re.search(r"\d", slug) and category_slug(slug):
            key = "pichau-" + sha256(slug.encode()).hexdigest()[:20]
    if not key:
        raise ValueError("Link não identifica uma página de produto específica")
    clean = urlunparse(("https", parsed.netloc, path, "", urlencode(kept), ""))
    return key, clean


def category_slug(slug):
    return any(word in slug for word in ("processador-", "placa-mae-", "memoria-", "ssd-", "fonte-", "kit-upgrade-"))
