from datetime import timedelta


def record_price(db, store, product_id, total_cents, observed_at):
    if type(total_cents) is not int or total_cents <= 0:
        raise ValueError("Preço deve ser um inteiro positivo em centavos")
    if observed_at.utcoffset() is None:
        raise ValueError("Data deve incluir fuso horário")
    # Uma amostra por dia evita que coletas frequentes distorçam a média.
    from datetime import timezone
    observed_at = observed_at.astimezone(timezone.utc)
    db.execute("""INSERT INTO prices VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(store, product_id, day) DO UPDATE SET
        total_cents=excluded.total_cents, observed_at=excluded.observed_at
        WHERE excluded.observed_at > prices.observed_at""",
        (store, product_id, observed_at.date().isoformat(), total_cents, observed_at.isoformat()))
    db.commit()


def historical_average(db, store, product_id, now, days):
    rows = db.execute("""SELECT total_cents FROM prices
        WHERE store=? AND product_id=? AND day>=? AND day<?""",
        (store, product_id, (now - timedelta(days=days)).date().isoformat(),
         now.date().isoformat())).fetchall()
    return (sum(row[0] for row in rows) / len(rows), len(rows)) if rows else (None, 0)
