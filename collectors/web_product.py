"""Coleta de páginas reais; não contorna login, captcha ou bloqueios."""
import json
import re
from decimal import Decimal, InvalidOperation

from collectors.catalog import store_for_url
from database.models import Offer


def cents(value):
    raw = str(value).replace("R$", "").replace("\xa0", "").strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        number = Decimal(raw)
        if not number.is_finite() or number <= 0:
            raise ValueError("Preço inválido")
        return int((number * 100).quantize(Decimal("1")))
    except InvalidOperation as exc:
        raise ValueError("Preço inválido") from exc


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def kabum_shipped_by(soup, seller):
    from services.seller_trust import normalized_name
    labels = soup.find_all(string=lambda text: text and text.strip() == "Vendido e entregue por:")
    providers = []
    for label in labels:
        if label.parent.name in ("script", "style"):
            continue
        container = label.parent.parent
        text = container.get_text(" ", strip=True)
        match = re.fullmatch(r"Vendido e entregue por:\s*(.+)", text)
        if match:
            providers.append(match[1].strip())
    if len(providers) == 1 and normalized_name(providers[0]) == normalized_name(seller):
        return providers[0]
    return ""


def parse_product(html, entry):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    if entry["store"] == "kabum":
        script = soup.select_one("script#__NEXT_DATA__")
        if script:
            try:
                product = json.loads(script.get_text())["props"]["pageProps"]["product"]
                code = re.search(r"/produto/(\d+)", entry["url"])
                if not code or str(product["id"]) != code.group(1):
                    raise ValueError("Produto retornado não corresponde ao link cadastrado")
                # Campos verificados nas páginas reais; não usa oldPrice nem valores Prime.
                prices = product["prices"]
                payment = ""
                price = prices["price"]
                if re.search(r"vista\s+no\s+PIX", soup.get_text(" ", strip=True), re.I):
                    price = prices["priceWithDiscount"]
                    payment = "À vista no PIX"
                return Offer(entry["store"], entry["id"], product["title"],
                             product.get("sellerName", ""), cents(price), None, payment,
                             product.get("available") is True, entry["url"], False,
                             shipped_by=kabum_shipped_by(soup, product.get("sellerName", "")))
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("Formato da página KaBuM mudou; revisão necessária") from exc
    products = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            for node in walk(json.loads(script.get_text())):
                types = node.get("@type", [])
                if isinstance(types, str):
                    types = [types]
                if "Product" in types and node.get("offers"):
                    products.append(node)
        except (ValueError, TypeError):
            continue
    if len(products) != 1:
        raise ValueError("Produto estruturado ausente/ambíguo; revisão do coletor necessária")
    product = products[0]
    offers = product["offers"]
    if isinstance(offers, list):
        if len(offers) != 1:
            raise ValueError("Vários vendedores/preços; selecione uma oferta específica")
        offers = offers[0]
    if not isinstance(offers, dict) or "price" not in offers:
        raise ValueError("Preço exato ausente (faixas e preços riscados são ignorados)")
    if offers.get("priceCurrency") != "BRL":
        raise ValueError("Moeda BRL não confirmada")
    title = product.get("name", "").strip()
    if not title:
        raise ValueError("Título ausente")
    seller = offers.get("seller", {})
    seller = seller.get("name", "") if isinstance(seller, dict) else ""
    return Offer(entry["store"], entry["id"], title, seller.strip(),
                 cents(offers["price"]), None, entry.get("payment_terms", ""),
                 str(offers.get("availability", "")).rsplit("/", 1)[-1] == "InStock",
                 entry.get("affiliate_url") or entry["url"],
                 entry.get("affiliate_allowed_whatsapp") is True,
                 shipped_by=kabum_shipped_by(soup, seller) if entry["store"] == "kabum" else "")


def collect(entry, browser, client=None):
    store = store_for_url(entry["url"])
    if store != entry["store"]:
        raise ValueError("Domínio incompatível com a loja cadastrada")
    page = browser.new_page(locale="pt-BR")
    try:
        from services.browser_http import navigate
        navigate(page, entry["url"], client, "product_lookup", 45000)
        if store_for_url(page.url) != store:
            raise ValueError("Redirecionamento para outra loja")
        page.wait_for_timeout(2500)
        body = page.locator("body").inner_text().lower()
        if any(text in body for text in ("digite os caracteres", "confirme que você é humano", "verify you are human", "robot check")):
            if client:
                client.fail("access_denied")
            raise ValueError("Verificação humana solicitada; coleta interrompida")
        return parse_product(page.content(), entry)
    finally:
        page.close()
