"""API oficial: recurso de itens ou catálogo escolhido explicitamente, sem fallback."""
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

from collectors.base import SourceError
from collectors.catalog import canonical_product, store_for_url
from collectors.web_product import cents
from database.models import Offer
from services.http_client import JsonHttpClient
from services.niche import category_for
from services.secrets import secret


# Domínios verificados nas respostas reais do catálogo MLB. O domínio de SSD
# também contém HDDs: o título continua sujeito à classificação estrita.
CATALOG_DOMAINS = {
    'processador': 'MLB-COMPUTER_PROCESSORS',
    'placa_mae': 'MLB-COMPUTER_MOTHERBOARDS',
    'memoria_ram': 'MLB-RAM_MEMORY_MODULES',
    'ssd': 'MLB-HARD_DRIVES_AND_SSDS',
    'fonte': 'MLB-DESKTOP_COMPUTER_POWER_SUPPLIES',
    'placa_video': 'MLB-GRAPHICS_CARDS',
}


class MercadoLivreSource:
    store = "mercadolivre"
    mode = "official_api"
    discovery_version = 'hardware-domains-v2'

    def __init__(self, db, options, client=None):
        self.options = options
        if options.get("api_resource", "items") not in ("items", "catalog"):
            raise ValueError("api_resource deve ser items ou catalog")
        self.catalog_mode = options.get("api_resource") == "catalog"
        if self.catalog_mode:
            self.mode = "official_catalog"
        self.token = secret(options.get("token_env", "ML_ACCESS_TOKEN"))
        self.cloud_oauth = options.get("oauth_mode") == "supabase"
        if self.cloud_oauth:
            self.token = ""
        self._oauth_error = False
        fingerprint = hashlib.sha256(self.token.encode()).hexdigest()[:16]
        self.client = client or JsonHttpClient(db, self.store, "mercadolivre:" + self.mode + ":" + fingerprint)
        self._search_cache = None

    def status(self):
        if self.cloud_oauth:
            if self._oauth_error:
                return {"state": "oauth_pending", "error": "OAuth HTTPS pendente ou indisponível; execute autorizar-mercadolivre.py status"}
            if not secret("SUPABASE_PROJECT_URL") or len(secret("BOT_API_SECRET")) < 32:
                return {"state": "needs_credentials", "error": "Configure SUPABASE_PROJECT_URL e BOT_API_SECRET para OAuth HTTPS"}
            return self.client.health()
        if not self.token:
            return {"state": "needs_credentials", "error": "Configure ML_ACCESS_TOKEN em .env e confirme as permissões da aplicação"}
        return self.client.health()

    def search(self, category, limit):
        if self.catalog_mode:
            return self._catalog_search(category, limit)
        # Não pressupõe busca global liberada: cadastra IDs específicos conhecidos.
        state = self.status()
        if "error" in state:
            raise SourceError(state["state"], state["error"])
        if self._search_cache is None:
            self._search_cache = []
            for item in self.options.get("item_ids", []):
                if not re.fullmatch(r"MLB\d+", str(item)):
                    raise SourceError("invalid_configuration", "item_ids deve conter IDs MLB numéricos")
                url = "https://produto.mercadolivre.com.br/MLB-" + item[3:] + "-_JM"
                entry = {"id": "ml-" + item, "store": self.store, "url": url, "enabled": True, "source": self.mode}
                entry["category"] = category_for(self.collect(entry).title)
                self._search_cache.append(entry)
        return [entry for entry in self._search_cache if entry["category"] == category][:limit]

    def collect(self, entry):
        if self.catalog_mode:
            return self._catalog_collect(entry)
        state = self.status()
        if "error" in state:
            raise SourceError(state["state"], state["error"])
        key, _ = canonical_product(entry["url"])
        item_id = key.removeprefix("ml-")
        if not re.fullmatch(r"MLB\d+", item_id):
            raise SourceError("invalid_item", "Informe um item_id específico; IDs de catálogo não bastam")
        if self.cloud_oauth and not self.token:
            from services.cloud import ml_cloud_token
            try:
                self.token = ml_cloud_token()
            except RuntimeError:
                self._oauth_error = True
                raise SourceError("oauth_pending", "OAuth HTTPS pendente ou indisponível; execute autorizar-mercadolivre.py status") from None
        data = self.client.get("https://api.mercadolibre.com/items/" + item_id,
                               headers={"Authorization": "Bearer " + self.token, "Accept": "application/json"},
                               operation="item_lookup")
        if not isinstance(data, dict) or data.get("id") != item_id or data.get("currency_id") != "BRL":
            raise SourceError("invalid_response", "Item ou moeda incompatível com o anúncio solicitado")
        if data.get("variations"):
            raise SourceError("variant_review", "Anúncio tem variantes; seleção explícita ainda necessária")
        seller = data.get("seller_id")
        if not isinstance(seller, int) or seller <= 0 or not data.get("title"):
            raise SourceError("invalid_response", "API não confirmou vendedor e título")
        url = data.get("permalink") or entry["url"]
        if store_for_url(url) != self.store or canonical_product(url)[0] != key:
            raise SourceError("invalid_response", "Permalink não corresponde ao item consultado")
        quantity = data.get("available_quantity")
        minimum = data.get("min_purchase_unit", 1)
        available = (data.get("status") == "active" and data.get("condition") == "new"
                     and type(minimum) is int and minimum == 1
                     and isinstance(quantity, (int, float)) and quantity > 0)
        return Offer(self.store, entry["id"], data["title"], str(seller), cents(data.get("price")),
                     None, "Preço do anúncio na API; confira as condições de pagamento na loja",
                     available, url, False, source=self.mode,
                     observed_at=datetime.now(timezone.utc).isoformat(), price_basis="api_item_price",
                     official_store_id=data.get("official_store_id"),
                     availability_evidence="quantity" if available else "unknown")

    def _catalog_get(self, path, operation):
        state = self.status()
        if "error" in state:
            raise SourceError(state["state"], state["error"])
        if self.cloud_oauth and not self.token:
            from services.cloud import ml_cloud_token
            try:
                self.token = ml_cloud_token()
            except RuntimeError:
                self._oauth_error = True
                raise SourceError("oauth_pending", "OAuth HTTPS indisponível") from None
        return self.client.get("https://api.mercadolibre.com" + path,
                               headers={"Authorization": "Bearer " + self.token, "Accept": "application/json"},
                               operation=operation)

    def _catalog_search(self, category, limit):
        from collectors.discovery import QUERIES
        limit = max(0, min(int(limit), 20))
        if not limit:
            return []
        products_limit = max(1, min(int(self.options.get('catalog_products_per_category', 5)), 10))
        params = {"status": "active", "site_id": "MLB", "q": QUERIES[category], "limit": products_limit}
        if category in CATALOG_DOMAINS:
            params['domain_id'] = CATALOG_DOMAINS[category]
        configured = self.options.get("catalog_ids", {}).get(category, [])
        if configured:
            if not isinstance(configured, list) or any(not re.fullmatch(r"MLB\d+", str(pid)) for pid in configured):
                raise SourceError("invalid_configuration", "catalog_ids deve conter listas de IDs MLB por categoria")
            data = {"results": [self._catalog_get("/products/" + pid, "catalog_product") for pid in configured[:products_limit]]}
        else:
            data = self._catalog_get("/products/search?" + urlencode(params), "catalog_search")
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise SourceError("invalid_response", "Busca de catálogo inválida")
        found = {}
        for product in data["results"][:products_limit]:
            pid = product.get("id", "")
            if (not re.fullmatch(r"MLB\d+", str(pid)) or product.get("status") != "active"
                    or category_for(product.get("name", "")) != category):
                continue
            try:
                items = self._catalog_items(pid)
            except SourceError as exc:
                if exc.state == "not_found":
                    continue
                raise
            for item in items:
                iid = item.get("item_id", "")
                if not re.fullmatch(r"MLB\d+", str(iid)) or item.get("site_id") != "MLB":
                    continue
                minimum = item.get("min_purchase_unit", 1)
                if type(minimum) is not int or minimum != 1 or item.get("condition") != "new":
                    continue
                official = item.get("official_store_id")
                if type(official) is not int or official <= 0:
                    continue
                url = "https://www.mercadolivre.com.br/p/" + pid + "?" + urlencode({"pdp_filters": "item_id:" + iid})
                found[iid] = {"id": "ml-" + iid, "store": self.store, "url": url,
                              "catalog_id": pid, "category": category, "enabled": True,
                              "source": self.mode, "title_hint": product["name"], "discovered": True}
                if len(found) >= limit:
                    return list(found.values())
        return list(found.values())

    def _catalog_items(self, pid):
        data = self._catalog_get("/products/" + pid + "/items?limit=100", "catalog_items")
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise SourceError("invalid_response", "Anúncios do catálogo inválidos")
        return data["results"][:100]

    def _catalog_collect(self, entry):
        pid = entry.get("catalog_id", "")
        if not re.fullmatch(r"MLB\d+", str(pid)):
            raise SourceError("catalog_mapping_required", "Link manual precisa do catalog_id confirmado; endpoint /items não será usado")
        key, _ = canonical_product(entry["url"])
        if entry["id"] != key:
            raise SourceError("invalid_item", "Identidade do anúncio inconsistente")
        product = self._catalog_get("/products/" + pid, "catalog_product")
        if (not isinstance(product, dict) or product.get("id") != pid
                or product.get("status") != "active" or not category_for(product.get("name", ""))):
            raise SourceError("invalid_response", "Produto de catálogo incompatível ou fora do nicho")
        item = next((row for row in self._catalog_items(pid) if row.get("item_id") == key.removeprefix("ml-")), None)
        if item is None:
            raise SourceError("catalog_item_missing", "Anúncio ausente na página limitada do catálogo; não publicar")
        seller = item.get("seller_id")
        if (item.get("site_id") != "MLB" or item.get("currency_id") != "BRL"
                or type(seller) is not int or seller <= 0):
            raise SourceError("invalid_response", "API não confirmou moeda, site e vendedor")
        minimum = item.get("min_purchase_unit", 1)
        if type(minimum) is not int or minimum != 1:
            raise SourceError("wholesale_review", "Anúncio exige múltiplas unidades ou compra mínima desconhecida")
        price = cents(item.get("price"))
        if price <= 0:
            raise SourceError("invalid_response", "Preço inválido")
        quantity = item.get("available_quantity")
        # Quantidade pode ser privada para terceiros. Um winner só serve como
        # evidência quando corresponde ao mesmo anúncio, vendedor, moeda e preço.
        available = (item.get("status") == "active" and item.get("condition") == "new"
                     and type(quantity) in (int, float) and quantity > 0)
        availability_evidence = "quantity" if available else "unknown"
        winner = product.get("buy_box_winner")
        if not available and isinstance(winner, dict) and item.get("status") in (None, "active"):
            winner_quantity = winner.get("available_quantity")
            available = (winner.get("item_id") == item["item_id"] and winner.get("seller_id") == seller
                         and winner.get("currency_id") == "BRL" and winner.get("price") == item.get("price")
                         and type(winner_quantity) in (int, float) and winner_quantity > 0
                         and item.get("condition") == "new"
                         and (quantity is None or (type(quantity) in (int,float) and quantity > 0)))
            if available:
                availability_evidence = "buy_box_winner"
        return Offer(self.store, key, product["name"], str(seller), price, None,
                     "Preço do anúncio no catálogo; confira pagamento na loja", available, entry["url"], False,
                     source=self.mode, observed_at=datetime.now(timezone.utc).isoformat(),
                     price_basis="catalog_item_price", official_store_id=item.get("official_store_id"),
                     availability_evidence=availability_evidence)
