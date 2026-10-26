"""Preços observados, separados do histórico elegível para aprovar ofertas."""
from datetime import timezone


def record_observation(db, offer, observed_at):
    """Preserva a última observação original de cada dia, inclusive estoque desconhecido."""
    if type(offer.price_cents) is not int or offer.price_cents <= 0:
        raise ValueError("Preço deve ser um inteiro positivo em centavos")
    if observed_at.utcoffset() is None:
        raise ValueError("Data deve incluir fuso horário")
    for field in ("store", "product_id", "source", "seller_id", "payment_terms", "price_basis"):
        value = getattr(offer, field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Observação precisa de identidade, vendedor, origem e base de preço")
    if type(offer.available) is not bool or not isinstance(offer.availability_evidence, str):
        raise ValueError("Disponibilidade e sua evidência têm tipos inválidos")
    observed_at = observed_at.astimezone(timezone.utc)
    db.execute("""CREATE TABLE IF NOT EXISTS price_observations (
        store TEXT NOT NULL, product_id TEXT NOT NULL, day TEXT NOT NULL,
        price_cents INTEGER NOT NULL CHECK(price_cents > 0), observed_at TEXT NOT NULL,
        source TEXT NOT NULL, seller_id TEXT NOT NULL, payment_terms TEXT NOT NULL,
        price_basis TEXT NOT NULL, available INTEGER NOT NULL CHECK(available IN (0, 1)),
        availability_evidence TEXT NOT NULL,
        PRIMARY KEY(store, product_id, day)
    )""")
    db.execute("""INSERT INTO price_observations (
        store, product_id, day, price_cents, observed_at, source, seller_id,
        payment_terms, price_basis, available, availability_evidence
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(store, product_id, day) DO UPDATE SET
        price_cents=excluded.price_cents, observed_at=excluded.observed_at,
        source=excluded.source, seller_id=excluded.seller_id,
        payment_terms=excluded.payment_terms, price_basis=excluded.price_basis,
        available=excluded.available, availability_evidence=excluded.availability_evidence
        WHERE excluded.observed_at > price_observations.observed_at""",
        (offer.store, offer.product_id, observed_at.date().isoformat(), offer.price_cents,
         observed_at.isoformat(), offer.source, offer.seller_id, offer.payment_terms,
         offer.price_basis, int(offer.available), offer.availability_evidence))
    db.commit()
