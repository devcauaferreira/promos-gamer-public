from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    database_path: Path = Path("database/promos.sqlite3")
    minimum_discount_percent: float = 25.0
    history_days: int = 30
    minimum_history_days: int = 1
    repeat_hours: int = 24
    trusted_sellers: frozenset[tuple[str, str]] = frozenset()
    include_shipping: bool = False
    require_affiliate: bool = False
