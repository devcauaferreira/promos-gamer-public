from dataclasses import dataclass
from datetime import timedelta

from services.affiliate_links import valid_affiliate_link
from services.price_history import historical_average
from services.seller_trust import seller_rejection


@dataclass(frozen=True)
class Decision:
    status: str
    average_cents: float | None
    discount_percent: float | None
    reasons: tuple[str, ...]


def evaluate(db, offer, config, now, channel="whatsapp"):
    average, samples = historical_average(db, offer.store, offer.product_id, now, config.history_days)
    discount = (1 - offer.total_cents / average) * 100 if average else None
    reasons = []
    if samples < config.minimum_history_days:
        reasons.append("Histórico insuficiente")
    if discount is None or discount < config.minimum_discount_percent:
        reasons.append("Queda abaixo do mínimo exigido")
    seller_reason = seller_rejection(offer, config.trusted_sellers)
    if seller_reason:
        reasons.append(seller_reason)
    if not offer.available:
        reasons.append("Disponibilidade não confirmada" if offer.availability_evidence in ('unknown', 'review_bundle_only')
                       else "Oferta indisponível")
    if offer.price_cents <= 0 or (config.include_shipping and (offer.shipping_cents is None or offer.shipping_cents < 0)):
        reasons.append("Preço ou frete inválido/desconhecido")
    if not offer.payment_terms.strip():
        reasons.append("Condições de pagamento desconhecidas")
    if config.require_affiliate and not valid_affiliate_link(offer):
        reasons.append("Link de afiliado inválido ou sem autorização no canal")
    cutoff = (now - timedelta(hours=config.repeat_hours)).isoformat()
    if db.execute("""SELECT 1 FROM publications WHERE store=? AND product_id=?
        AND channel=? AND published_at>=? LIMIT 1""",
        (offer.store, offer.product_id, channel, cutoff)).fetchone():
        reasons.append("Oferta publicada recentemente")
    return Decision("pending_review" if reasons else "approved", average, discount, tuple(reasons))


def mark_published(db, offer, channel, now):
    """Chamar somente após confirmação de envio pelo canal."""
    db.execute("INSERT INTO publications VALUES (?, ?, ?, ?)",
               (offer.store, offer.product_id, channel, now.isoformat()))
    db.commit()
