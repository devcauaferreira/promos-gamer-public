def money(cents):
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_message(offer, decision):
    from services.niche import CATEGORIES, category_for
    category = category_for(offer.title)
    heading = f"PROMOS GAMER • {CATEGORIES[category].upper()}" if category else "PROMOS GAMER • OFERTA GAMER"
    lines = [f"🎮 *{heading}*", f"*{offer.title}*", ""]
    lines.append(f"🔥 *Por {money(offer.price_cents)}*")
    if decision.average_cents is not None and decision.discount_percent is not None:
        lines.append(f"📉 {decision.discount_percent:.1f}% abaixo da média observada".replace(".", ","))
    unconfirmed_ml_catalog = (offer.store == "mercadolivre"
                              and offer.source == "official_catalog"
                              and offer.availability_evidence == "unknown")
    unconfirmed_amazon_feed = (offer.store == "amazon"
                               and offer.source == "authorized_feed"
                               and offer.availability_evidence == "unknown")
    unconfirmed_stock = unconfirmed_ml_catalog or unconfirmed_amazon_feed
    if unconfirmed_stock:
        store_location = "no Mercado Livre" if unconfirmed_ml_catalog else "na Amazon"
        lines.extend(["", "⚠️ *ESTOQUE NÃO CONFIRMADO*",
                      f"Confirme a disponibilidade e as condições de pagamento {store_location} antes de comprar."])
    if decision.average_cents is not None:
        lines.extend(["", "📊 *HISTÓRICO DE PREÇOS*",
                      f"Média dos últimos {decision.history_days} dias: {money(decision.average_cents)}"])
        if decision.history_samples:
            unit = "dia" if decision.history_samples == 1 else "dias"
            lines.append(f"Observado em {decision.history_samples} {unit} de coleta")
    lines.append("")

    seller_details = []
    if offer.store.strip():
        seller_details.append(offer.store.strip().title())
    if offer.seller_id.strip():
        seller_details.append(f"Vendedor: {offer.seller_id.strip()}")
    if seller_details:
        lines.append("🏬 " + " • ".join(seller_details))
    if offer.shipped_by.strip():
        lines.append(f"🚚 Entregue por: {offer.shipped_by.strip()}")
    if offer.payment_terms.strip() and not unconfirmed_stock:
        lines.append(f"💳 {offer.payment_terms.strip()}")
    if offer.affiliate_url.strip():
        lines.extend(["", "🛒 *COMPRE AQUI*", offer.affiliate_url.strip()])
    lines.extend(["", "Frete não incluído. Confira preço e disponibilidade na loja.",
                  "— *Promos Gamer*"])
    return "\n".join(lines)
