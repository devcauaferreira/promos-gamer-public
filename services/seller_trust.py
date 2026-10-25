"""Critérios automáticos de vendedor definidos para as cinco lojas."""
import re


DIRECT_NAMES = {
    "amazon": {"amazon", "amazon.com.br"},
    "kabum": {"kabum", "kabum!"},
    "magalu": {"magalu", "magazine luiza"},
    "pichau": {"pichau", "pichau informática"},
}


def normalized_name(value):
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def seller_rejection(offer, trusted_sellers=()):
    if offer.store == "demo" and (offer.store, offer.seller_id) in trusted_sellers:
        return None
    if offer.store == "mercadolivre":
        if (offer.source in ("official_api", "official_catalog", "authorized_feed")
                and type(offer.official_store_id) is int and offer.official_store_id > 0
                and str(offer.seller_id).isdigit() and int(offer.seller_id) > 0):
            return None
        return "Anúncio sem loja oficial confirmada pelo Mercado Livre"
    names = DIRECT_NAMES.get(offer.store, set())
    if normalized_name(offer.seller_id) not in names:
        return "Produto não vendido pela própria loja"
    if normalized_name(offer.shipped_by) not in names:
        return "Entrega pela própria loja não confirmada"
    return None
