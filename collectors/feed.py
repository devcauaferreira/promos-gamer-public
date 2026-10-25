"""Contrato local para dados obtidos de um fornecedor autorizado; não é API de loja."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collectors.base import SourceError
from collectors.catalog import canonical_product, store_for_url
from database.models import Offer
from services.niche import category_for


class AuthorizedFeed:
    mode = "authorized_feed"

    def __init__(self, store, options):
        self.store, self.options = store, options

    def status(self):
        if not self.options.get("authorization_reference") or not self.options.get("feed_path"):
            return {"state": "needs_authorized_feed", "error": "Configure um feed e a referência de autorização do fornecedor"}
        if not Path(self.options["feed_path"]).is_file():
            return {"state": "feed_missing", "error": "Arquivo de feed ainda não está disponível"}
        return {"state": "ready_to_validate"}

    def offers(self):
        state = self.status()
        if "error" in state:
            raise SourceError(state["state"], state["error"])
        file = Path(self.options["feed_path"])
        if file.stat().st_size > 10_000_000:
            raise SourceError("invalid_feed", "Feed maior que 10 MB")
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
            if payload["store"] != self.store or payload.get("schema_version") != 1:
                raise ValueError()
            now = datetime.now(timezone.utc)
            oldest = now - timedelta(minutes=int(self.options.get("max_age_minutes", 60)))
            offers = {}
            for row in payload["offers"]:
                observed = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
                if observed.utcoffset() is None or observed < oldest or observed > now + timedelta(minutes=5):
                    raise SourceError("stale_feed", "Feed expirado ou com data inválida; atualize a fonte")
                if row.get("currency") != "BRL" or type(row["price_cents"]) is not int or row["price_cents"] <= 0:
                    raise ValueError()
                if store_for_url(row["url"]) != self.store or type(row["available"]) is not bool:
                    raise ValueError()
                key, url = canonical_product(row["url"])
                if not row["seller_id"] or not row["payment_terms"] or not row["title"] or key in offers:
                    raise ValueError()
                official = row.get("official_store_id")
                shipped_by = row.get("shipped_by", "")
                if (official is not None and (type(official) is not int or official <= 0)) or not isinstance(shipped_by, str):
                    raise ValueError()
                offers[key] = Offer(self.store, key, row["title"], str(row["seller_id"]), row["price_cents"], None,
                                    row["payment_terms"], row["available"], url, False,
                                    source="authorized_feed", observed_at=observed.astimezone(timezone.utc).isoformat(),
                                    price_basis=row.get("price_basis", "feed_price"),
                                    official_store_id=official, shipped_by=shipped_by)
            return offers
        except SourceError:
            raise
        except (ValueError, KeyError, TypeError, OSError):
            raise SourceError("invalid_feed", "Feed inválido; confira o contrato documentado") from None

    def search(self, category, limit):
        return [{"id": key, "store": self.store, "url": offer.affiliate_url,
                 "category": category, "enabled": True, "source": self.mode}
                for key, offer in self.offers().items() if category_for(offer.title) == category][:limit]

    def collect(self, entry):
        key, _ = canonical_product(entry["url"])
        offer = self.offers().get(key)
        if offer is None:
            raise SourceError("item_missing", "Produto não está no feed atualizado")
        return replace(offer, product_id=entry["id"])
