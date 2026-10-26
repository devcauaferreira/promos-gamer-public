import json
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from collectors.registry import LazyBrowser, build_sources, source_report
from collectors.base import SourceError
from database.models import connect
from publishers.whatsapp import publish
from services.discount_filter import evaluate, mark_published
from services.message_builder import build_message
from services.price_history import record_price
from services.settings import load_settings
from collectors.discovery import discover, tracked_entries
from collectors.catalog import canonical_product
from services.niche import category_for
from services.outbox import ensure_outbox, enqueue, pending, set_state, same_offer


def cycle(send=False, visible=False, discover_only=False, force_discovery=False, checkpoint=None, queued_only=False):
    config, settings = load_settings()
    group = settings.get("whatsapp_group_id", "")
    if send and not group.endswith("@g.us"):
        raise ValueError("Crie um grupo e configure whatsapp_group_id antes de enviar")
    report = []
    candidates = []
    with closing(connect(config.database_path)) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS dispatches (
            store TEXT, product_id TEXT, channel TEXT, state TEXT,
            message_id TEXT, updated_at TEXT,
            PRIMARY KEY(store, product_id, channel))""")
        db.commit()
        ensure_outbox(db)
        browser = LazyBrowser(visible)
        sources = build_sources(db, settings, browser)
        try:
            discovery_report = [] if queued_only else discover(db, browser, settings, force=force_discovery, sources=sources)
            Path("reports").mkdir(exist_ok=True)
            Path("reports/sources.json").write_text(json.dumps(source_report(sources), ensure_ascii=False, indent=2), encoding="utf-8")
            if discovery_report:
                Path("reports/discovery.json").write_text(json.dumps(discovery_report, ensure_ascii=False, indent=2), encoding="utf-8")
            if discover_only:
                return discovery_report
            queued = pending(db) if queued_only else []
            expected = {(entry['store'], entry['id']): offer for entry, offer in queued}
            manual = ([entry for entry, _ in queued] if queued_only else
                      json.loads(Path("products.json").read_text(encoding="utf-8")) if Path("products.json").exists() else [])
            unique = {}
            for entry in manual:
                try:
                    key, _ = canonical_product(entry["url"])
                except ValueError:
                    key = entry["id"]
                unique[key] = entry
            for entry in ([] if queued_only else tracked_entries(db, int(settings.get("discovery", {}).get("max_products_per_run", 20)))):
                unique.setdefault(entry["id"], entry)
            entries = list(unique.values())
            for entry in entries:
                if not entry.get("enabled", True):
                    continue
                row = {"store": entry["store"], "id": entry["id"], "url": entry["url"]}
                try:
                    offer = sources[entry["store"]].collect(entry)
                    original = expected.get((entry['store'], entry['id']))
                    if original and not same_offer(offer, original):
                        set_state(db, entry, 'stale')
                        row.update(status='stale', reason='Candidato mudou desde a coleta; aguarda nova avaliação')
                        continue
                    category = category_for(offer.title)
                    if category is None:
                        row.update(status="excluded", reason="Produto fora das sete categorias de hardware")
                        report.append(row)
                        continue
                    row["category"] = category
                    now = datetime.now(timezone.utc)
                    # Isola histórico por vendedor e forma de pagamento; sem frete.
                    basis = f"{offer.seller_id}|{offer.payment_terms}|product-only"
                    if offer.source != "legacy_web":
                        basis += f"|{offer.source}|{offer.price_basis}"
                    context = sha256(basis.encode()).hexdigest()[:12]
                    from dataclasses import replace
                    offer = replace(offer, product_id=f"{entry['id']}:{context}")
                    channel = "whatsapp:" + group
                    decision = evaluate(db, offer, config, now, channel)
                    row.update(offer=asdict(offer), decision=asdict(decision), message=build_message(offer, decision))
                    if offer.available and offer.seller_id and offer.payment_terms:
                        observed_at = datetime.fromisoformat(offer.observed_at) if offer.observed_at else now
                        record_price(db, offer.store, offer.product_id, offer.price_cents, observed_at)
                    else:
                        row["history_skipped"] = "Estoque, vendedor ou pagamento não confirmado"
                    if send and decision.status == "approved":
                        candidates.append((entry, offer, decision, row))
                    elif not send and decision.status == "approved":
                        enqueue(db, entry, offer, now)
                    elif queued_only:
                        set_state(db, entry, 'rejected')
                except SourceError as exc:
                    row.update(status=exc.state, error=str(exc))
                except Exception as exc:
                    row["error"] = str(exc)
                finally:
                    db.execute("UPDATE tracked_products SET last_checked=? WHERE id=?",
                               (datetime.now(timezone.utc).isoformat(), entry["id"]))
                    db.commit()
                    if row.get('status') == 'stale':
                        report.append(row)
                report.append(row)
                print(f"{entry['store']} {entry['id']}: {row.get('error') or row.get('send_status') or row.get('decision', {}).get('status', 'pending_review')}", flush=True)
            candidates.sort(key=lambda item: (-item[2].discount_percent, item[1].price_cents))
            sent = 0
            for entry, offer, decision, row in candidates:
                if sent >= int(settings.get("max_messages_per_run", 10)):
                    row["send_status"] = "queued: limite desta execução; será reavaliada no próximo ciclo"
                    continue
                dispatch_attempted = False
                previous_dispatch = None
                try:
                    # Confere novamente o anúncio: a busca de todas as lojas pode demorar.
                    current = sources[entry["store"]].collect(entry)
                    if (current.price_cents, current.seller_id, current.payment_terms, current.available,
                        current.official_store_id, current.shipped_by) != (offer.price_cents, offer.seller_id,
                        offer.payment_terms, offer.available, offer.official_store_id, offer.shipped_by):
                        row["send_status"] = "skipped: anúncio mudou durante a execução"
                        set_state(db, entry, 'stale')
                        continue
                    previous_dispatch = db.execute(
                        "SELECT state,message_id,updated_at FROM dispatches WHERE store=? AND product_id=? AND channel=?",
                        (offer.store, offer.product_id, "whatsapp:" + group)).fetchone()
                    dispatch_attempted = True
                    if dispatch(db, offer, row["message"], config, group, checkpoint=checkpoint):
                        row["send_status"] = "sent"
                        set_state(db, entry, 'sent')
                        sent += 1
                    else:
                        row["send_status"] = "blocked: repetição ou tentativa incerta"
                        set_state(db, entry, 'blocked')
                except Exception as exc:
                    current_dispatch = (db.execute(
                        "SELECT state,message_id,updated_at FROM dispatches WHERE store=? AND product_id=? AND channel=?",
                        (offer.store, offer.product_id, "whatsapp:" + group)).fetchone()
                        if dispatch_attempted else None)
                    changed = current_dispatch is not None and current_dispatch != previous_dispatch
                    if changed and current_dispatch[0] == 'sent':
                        row["send_status"] = "sent"
                        row["persistence_error"] = str(exc)
                        set_state(db, entry, 'sent')
                        sent += 1
                    else:
                        row["send_error"] = str(exc)
                        retryable = not dispatch_attempted or not changed or current_dispatch[0] == 'failed_before_send'
                        set_state(db, entry, 'pending' if retryable else 'uncertain')
                print(f"Envio {entry['id']}: {row.get('send_status') or row.get('send_error')}", flush=True)
        finally:
            Path("reports").mkdir(exist_ok=True)
            Path("reports/sources.json").write_text(json.dumps(source_report(sources), ensure_ascii=False, indent=2), encoding="utf-8")
            browser.close()
            if checkpoint:
                checkpoint(db)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Relatório: reports/latest.json")
    return report


def dispatch(db, offer, message, config, group, checkpoint=None):
    now = datetime.now(timezone.utc)
    channel = "whatsapp:" + group
    db.execute("BEGIN IMMEDIATE")
    previous = db.execute("SELECT state FROM dispatches WHERE store=? AND product_id=? AND channel=?",
                          (offer.store, offer.product_id, channel)).fetchone()
    fresh = evaluate(db, offer, config, now, channel)
    if (previous and previous[0] in ("sending", "uncertain")) or fresh.status != "approved":
        db.rollback()
        return False
    db.execute("INSERT OR REPLACE INTO dispatches VALUES (?, ?, ?, 'sending', NULL, ?)",
               (offer.store, offer.product_id, channel, now.isoformat()))
    db.commit()
    # Uma falha de reserva remota ocorre antes de qualquer tentativa no WhatsApp.
    # Não deve tornar permanentemente incerto um envio que não foi iniciado.
    try:
        if checkpoint:
            checkpoint(db)
    except Exception:
        db.execute("UPDATE dispatches SET state='failed_before_send' WHERE store=? AND product_id=? AND channel=?",
                   (offer.store, offer.product_id, channel))
        db.commit()
        if checkpoint:
            try:
                checkpoint(db)
            except Exception:
                # Preserva a falha original. Se a persistência continuar indisponível,
                # o chamador conserva o erro e o estado local para reconciliação.
                pass
        raise
    try:
        message_id = publish(message, group, image_url=offer.image_url)
    except Exception:
        db.execute("UPDATE dispatches SET state='uncertain' WHERE store=? AND product_id=? AND channel=?",
                   (offer.store, offer.product_id, channel))
        db.commit()
        if checkpoint:
            try:
                checkpoint(db)
            except Exception:
                pass
        raise
    # A confirmação do WhatsApp já existe. Falhas de persistência posteriores
    # precisam ser reportadas sem reclassificar a entrega como incerta.
    mark_published(db, offer, channel, now)
    db.execute("UPDATE dispatches SET state='sent', message_id=? WHERE store=? AND product_id=? AND channel=?",
               (message_id, offer.store, offer.product_id, channel))
    db.commit()
    if checkpoint:
        checkpoint(db)
    return True
