"""Candidatos persistidos entre a coleta e a sessão do WhatsApp."""
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone


def ensure_outbox(db):
    db.execute("""CREATE TABLE IF NOT EXISTS pending_offers (
        store TEXT NOT NULL, entry_id TEXT NOT NULL, entry_json TEXT NOT NULL,
        offer_json TEXT NOT NULL, observed_at TEXT NOT NULL, state TEXT NOT NULL,
        PRIMARY KEY(store, entry_id))""")
    db.commit()


def enqueue(db, entry, offer, now):
    db.execute("INSERT OR REPLACE INTO pending_offers VALUES (?,?,?,?,?,'pending')",
               (offer.store, entry['id'], json.dumps(entry, ensure_ascii=False),
                json.dumps(asdict(offer), ensure_ascii=False), now.isoformat()))
    db.commit()


def pending(db, now=None):
    ensure_outbox(db)
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(minutes=30)).isoformat()
    db.execute("UPDATE pending_offers SET state='expired' WHERE state='pending' AND observed_at<?", (cutoff,))
    db.commit()
    return [(json.loads(entry), json.loads(offer)) for entry, offer in db.execute(
        "SELECT entry_json,offer_json FROM pending_offers WHERE state='pending' ORDER BY observed_at,store,entry_id")]


def set_state(db, entry, state):
    db.execute("UPDATE pending_offers SET state=? WHERE store=? AND entry_id=?",
               (state, entry['store'], entry['id']))
    db.commit()


def same_offer(current, expected):
    return all(getattr(current, key) == expected.get(key) for key in (
        'store', 'title', 'seller_id', 'price_cents', 'payment_terms', 'available',
        'official_store_id', 'shipped_by', 'source', 'price_basis', 'affiliate_url'))
