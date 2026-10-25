import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Offer:
    store: str
    product_id: str
    title: str
    seller_id: str
    price_cents: int
    shipping_cents: int | None
    payment_terms: str
    available: bool
    affiliate_url: str
    affiliate_allowed: bool = False
    source: str = "legacy_web"
    observed_at: str | None = None
    price_basis: str = "legacy_page_price"
    official_store_id: int | None = None
    shipped_by: str = ""

    @property
    def total_cents(self):
        return self.price_cents + (self.shipping_cents or 0)


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS prices (
            store TEXT NOT NULL, product_id TEXT NOT NULL,
            day TEXT NOT NULL, total_cents INTEGER NOT NULL CHECK(total_cents > 0),
            observed_at TEXT NOT NULL,
            PRIMARY KEY(store, product_id, day)
        );
        CREATE TABLE IF NOT EXISTS publications (
            store TEXT NOT NULL, product_id TEXT NOT NULL,
            channel TEXT NOT NULL, published_at TEXT NOT NULL
        );
    """)
    return db
