"""Busca limitada e persistente nos catálogos das cinco lojas."""
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin

from collectors.catalog import canonical_product, store_for_url
from services.niche import CATEGORIES, category_for

SEARCHES = {
    "amazon": "https://www.amazon.com.br/s?k={query}",
    "mercadolivre": "https://lista.mercadolivre.com.br/{slug}",
    "magalu": "https://www.magazineluiza.com.br/busca/{slug}/",
    "kabum": "https://www.kabum.com.br/busca/{slug}",
    "pichau": "https://www.pichau.com.br/search?q={query}",
}
QUERIES = {
    "processador": "processador",
    "placa_mae": "placa mae",
    "memoria_ram": "memoria ram",
    "ssd": "ssd",
    "fonte": "fonte atx",
    "placa_video": "placa de video",
    "kit_upgrade": "kit upgrade",
}


def search_url(store, category):
    query = QUERIES[category]
    return SEARCHES[store].format(query=quote(query), slug=quote(query.replace(" ", "-")))


def parse_links(html, base_url, store, category, limit):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for anchor in soup.select("a[href]"):
        url = urljoin(base_url, anchor["href"])
        try:
            if store_for_url(url) != store:
                continue
            key, url = canonical_product(url)
        except ValueError:
            continue
        title = anchor.get("title") or anchor.get_text(" ", strip=True)
        image = anchor.find("img", alt=True)
        if len(title) < 8 and image:
            title = image["alt"]
        detected = category_for(title)
        # Links sem título serão classificados pela página de detalhe antes de publicar.
        if detected and detected != category:
            continue
        if title and len(title) > 8 and not detected:
            continue
        if key not in found:
            found[key] = {"id": key, "store": store, "url": url, "category": category,
                          "title_hint": title, "enabled": True, "payment_terms": "", "discovered": True}
        if len(found) >= limit:
            break
    return list(found.values())


def discover(db, browser, settings, force=False, sources=None):
    from collectors.base import SourceError
    from collectors.registry import build_sources
    options = settings.get("discovery", {})
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tracked_products (
            id TEXT PRIMARY KEY, store TEXT NOT NULL, category TEXT NOT NULL,
            data TEXT NOT NULL, last_seen TEXT NOT NULL, last_checked TEXT
        );
        CREATE TABLE IF NOT EXISTS discovery_runs (
            store TEXT, category TEXT, checked_at TEXT, status TEXT,
            PRIMARY KEY(store, category)
        );
    """)
    if not options.get("enabled", True):
        return []
    sources = sources if sources is not None else build_sources(db, settings, browser)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=options.get("refresh_hours", 6))).isoformat()
    report = []
    blocked = {}
    for store in options.get("stores", list(SEARCHES)):
        source = sources[store]
        for category in options.get("categories", list(CATEGORIES)):
            health = source.status()
            if "error" in health:
                report.append({"store": store, "category": category, "source": source.mode,
                               "status": health["state"], "error": health["error"], "checked_at": now.isoformat()})
                continue
            previous = db.execute("SELECT checked_at,status FROM discovery_runs WHERE store=? AND category=?", (store, category)).fetchone()
            if not force and previous and previous[0] > cutoff:
                try:
                    row = json.loads(previous[1])
                except ValueError:
                    row = {"store": store, "category": category, "status": previous[1],
                           "found": db.execute("SELECT COUNT(*) FROM tracked_products WHERE store=? AND category=?", (store, category)).fetchone()[0]}
                empty_web_result = (source.mode == "legacy_web" and row.get("status") == "ok"
                                    and row.get("found") == 0)
                if row.get("source") == source.mode and not empty_web_result:
                    row.update(cached=True, checked_at=previous[0])
                    report.append(row)
                    continue
            if store in blocked:
                row = {"store": store, "category": category, "source": source.mode,
                       "status": "skipped", "error": blocked[store], "checked_at": now.isoformat()}
                report.append(row)
                db.execute("INSERT OR REPLACE INTO discovery_runs VALUES (?,?,?,?)", (store, category, now.isoformat(), json.dumps(row, ensure_ascii=False)))
                db.commit()
                continue
            row = {"store": store, "category": category, "source": source.mode, "checked_at": now.isoformat()}
            try:
                entries = source.search(category, int(options.get("products_per_category", 5)))
                for entry in entries:
                    db.execute("""INSERT INTO tracked_products(id,store,category,data,last_seen)
                        VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                        data=excluded.data, last_seen=excluded.last_seen""",
                        (entry["id"], store, category, json.dumps(entry, ensure_ascii=False), now.isoformat()))
                row.update(status="ok", found=len(entries))
            except SourceError as exc:
                row.update(status=exc.state, error=str(exc))
                blocked[store] = str(exc)
            except Exception as exc:
                row.update(status="error", error=str(exc))
            db.execute("INSERT OR REPLACE INTO discovery_runs VALUES (?,?,?,?)", (store, category, now.isoformat(), json.dumps(row, ensure_ascii=False)))
            db.commit()
            report.append(row)
            print(f"Busca {store}/{category}: {row.get('error') or str(row.get('found', 0)) + ' produtos'}", flush=True)
    return report


def tracked_entries(db, limit=20):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rows = db.execute("""SELECT data FROM tracked_products WHERE last_seen>=?
        ORDER BY COALESCE(last_checked, ''), store, category, id LIMIT ?""", (cutoff, limit)).fetchall()
    return [json.loads(row[0]) for row in rows]
