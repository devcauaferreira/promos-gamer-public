import json
from pathlib import Path

from config import Config


def load_settings(path="settings.json"):
    file = Path(path)
    data = json.loads(file.read_text(encoding="utf-8")) if file.exists() else {}
    config = Config(
        database_path=Path(data.get("database_path", "database/promos.sqlite3")),
        minimum_discount_percent=float(data.get("minimum_discount_percent", 25)),
        history_days=int(data.get("history_days", 30)),
        minimum_history_days=int(data.get("minimum_history_days", 1)),
        repeat_hours=int(data.get("repeat_hours", 24)),
        trusted_sellers=frozenset(tuple(pair) for pair in data.get("trusted_sellers", [])),
        include_shipping=False, require_affiliate=False)
    if not 0 < config.minimum_discount_percent < 100 or not 1 <= config.minimum_history_days <= config.history_days or config.repeat_hours < 1:
        raise ValueError("Limites inválidos em settings.json")
    if int(data.get("max_messages_per_run", 3)) < 1 or int(data.get("interval_seconds", 300)) < 300:
        raise ValueError("Use ao menos 1 mensagem e intervalo de 300 segundos")
    from collectors.discovery import SEARCHES
    from collectors.registry import DEFAULT_MODES
    from services.niche import CATEGORIES
    options = data.get("discovery", {})
    if any(store not in SEARCHES for store in options.get("stores", [])) or any(category not in CATEGORIES for category in options.get("categories", [])):
        raise ValueError("Loja ou categoria de busca inválida")
    if not 1 <= int(options.get("products_per_category", 5)) <= 50 or not 1 <= int(options.get("max_products_per_run", 20)) <= 500 or float(options.get("refresh_hours", 6)) < 1:
        raise ValueError("Limites de descoberta inválidos")
    for store, source in data.get("sources", {}).items():
        mode = source.get("mode", DEFAULT_MODES.get(store))
        allowed_modes = ('disabled', 'authorized_feed', DEFAULT_MODES.get(store))
        if store == 'amazon':
            allowed_modes += ('public_catalog_review',)
        if store not in DEFAULT_MODES or mode not in allowed_modes:
            raise ValueError("Modo de fonte não suportado")
        if mode == "authorized_feed" and not 1 <= int(source.get("max_age_minutes", 60)) <= 1440:
            raise ValueError("Validade do feed deve estar entre 1 e 1440 minutos")
    return config, data
