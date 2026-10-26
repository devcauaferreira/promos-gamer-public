"""Observações de página pública Amazon, explicitamente sem aprovação automática."""
import json
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener

from bs4 import BeautifulSoup
from collectors.base import SourceError
from collectors.catalog import canonical_product, store_for_url
from collectors.web_product import cents
from database.models import Offer
from services.diagnostics import response_metadata, write_diagnostic
from services.http_client import JsonHttpClient, NoRedirect, retry_seconds
from services.niche import category_for


def parse_amazon_review(html, entry):
    key, url = canonical_product(entry['url'])
    if store_for_url(url) != 'amazon' or urlparse(url).query:
        raise SourceError('invalid_item', 'Use um ASIN direto, sem selecionar outro vendedor')
    asin = key.removeprefix('amazon-')
    soup = BeautifulSoup(html, 'html.parser')
    identity = soup.select_one('input#ASIN')
    title = soup.select_one('#productTitle')
    if not identity or identity.get('value') != asin or not title:
        raise SourceError('invalid_response', 'Página não confirmou o ASIN e o título solicitados')
    name = title.get_text(' ', strip=True)
    if not category_for(name):
        raise SourceError('outside_niche', 'Produto fora das categorias de hardware')
    if soup.select_one('#outOfStock'):
        raise SourceError('item_unavailable', 'Produto indisponível na página observada')
    # Não usa .a-price global, preço mínimo de outros vendedores ou total de kits.
    cards = soup.select('#sims-productBundle_feature_div_0 '
                        '[data-csa-c-item-id="amzn1.asin.' + asin + '"]')
    if len(cards) != 1:
        raise SourceError('price_unconfirmed', 'Preço do próprio ASIN não foi confirmado')
    card = cards[0]
    root = card.find_parent(attrs={'data-components': True})
    try:
        data = json.loads(root['data-components'])[card['data-csa-c-pos']]
        price = data['price']
        if (price['currencyCode'] != 'BRL' or data.get('showPrice') is not True
                or data.get('suppressed') is not False or type(data.get('minQuantity')) is not int
                or data['minQuantity'] != 1):
            raise ValueError()
        amount = cents(str(price['wholeValue']) + ',' + str(price['fractionalValue']).zfill(2))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SourceError('price_unconfirmed', 'Preço unitário BRL e quantidade não confirmados no card exato') from None
    text = card.get_text(' ', strip=True)
    if not re.search(r'Enviado de e vendido por\s+Amazon\.com\.br\b', text, re.I):
        raise SourceError('seller_unconfirmed', 'Venda e entrega pela Amazon não confirmadas nesse contexto')
    if not re.search(r'\bEm estoque\b', text, re.I):
        raise SourceError('item_unavailable', 'Disponibilidade não confirmada no card')
    # Cotação do widget tem base própria; não equivale à buybox nem confirma
    # pagamento/compra avulsa. Guarda observação, mas não alimenta prices/envios.
    return Offer('amazon', entry['id'], name, 'Amazon.com.br', amount, None,
                 'Preço unitário em Compre junto; condição de compra avulsa não confirmada',
                 False, url, False, source='public_catalog_review',
                 observed_at=datetime.now(timezone.utc).isoformat(), price_basis='amazon_bundle_unit_quote',
                 shipped_by='Amazon.com.br', availability_evidence='review_bundle_only')


class AmazonPublicReview:
    store = 'amazon'
    mode = 'public_catalog_review'

    def __init__(self, db, options, opener=None):
        self.options = options
        self.client = JsonHttpClient(db, self.store, 'amazon:public_catalog_review')
        self.opener = opener or build_opener(NoRedirect())

    def status(self):
        health = self.client.health()
        if 'error' in health:
            return health
        return {'state': 'review_only', 'notice': 'Observações públicas; preço de compra avulsa não validado para publicação'}

    def search(self, category, limit):
        rows = []
        for item in self.options.get('products', []):
            key, url = canonical_product(item['url'])
            if store_for_url(url) != self.store or urlparse(url).query:
                raise SourceError('invalid_configuration', 'Produto de observação precisa de URL direta Amazon')
            if category_for(item.get('title_hint', '')) == category:
                rows.append({'id': key, 'url': url, 'store': self.store, 'category': category,
                             'enabled': True, 'source': self.mode})
        return rows[:limit]

    def collect(self, entry):
        state = self.status()
        if 'error' in state:
            raise SourceError(state['state'], state['error'])
        _, url = canonical_product(entry['url'])
        if store_for_url(url) != self.store or urlparse(url).query:
            raise SourceError('invalid_item', 'Use link direto Amazon sem outra seleção de vendedor')
        try:
            with self.opener.open(Request(url), timeout=20) as response:
                status, headers, body = response.status, response.headers, response.read(3_000_001)
        except HTTPError as error:
            status, headers = error.code, error.headers
            try:
                body = error.read(65536)
            finally:
                error.close()
        except (URLError, TimeoutError, OSError):
            self.client.fail('network_error', 900)
            raise SourceError('network_error', 'Falha de rede; consulta da fonte adiada') from None
        write_diagnostic(self.store, 'public_product_review', response_metadata(url, status, headers, body))
        if status in (401, 403):
            self.client.fail('access_denied')
            raise SourceError('access_denied', 'Acesso público negado; fonte suspensa sem novas tentativas automáticas')
        if status == 429 or status >= 500:
            retry = retry_seconds(headers.get('Retry-After'))
            state = 'rate_limited' if status == 429 else 'temporarily_unavailable'
            self.client.fail(state, max(900, retry or 0))
            raise SourceError(state, 'Fonte temporariamente indisponível; consulta adiada')
        if status != 200 or len(body) > 3_000_000:
            raise SourceError('invalid_response', 'Página pública não utilizável')
        text = BeautifulSoup(body, 'html.parser').get_text(' ', strip=True).casefold()
        if any(term in text for term in ('robot check', 'verify you are human', 'digite os caracteres', 'confirme que você é humano')):
            self.client.fail('access_denied')
            raise SourceError('access_denied', 'Verificação humana solicitada; fonte suspensa')
        offer = parse_amazon_review(body, entry)
        self.client.fail('operational')
        return offer
