def money(cents):
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_message(offer, decision):
    from services.niche import CATEGORIES, category_for
    category = category_for(offer.title)
    lines = [f"🔥 *OFERTA DE {CATEGORIES[category].upper()}*" if category else "🔥 *OFERTA GAMER*",
             "", f"*{offer.title}*", ""]
    if decision.average_cents is not None:
        lines.append(f"📉 Média dos últimos {decision.history_days} dias: {money(decision.average_cents)}")
    lines.append(f"💥 *Agora: {money(offer.price_cents)}*")
    if decision.average_cents is not None:
        lines.append(f"⬇️ {decision.discount_percent:.1f}% abaixo da média".replace(".", ","))
    lines.extend(["", f"🏬 {offer.store.title()} | Vendido por {offer.seller_id}",
                  f"💳 {offer.payment_terms}", "", "🛒 *Compre aqui:*", offer.affiliate_url,
                  "", "Frete não incluído. Confira preço e disponibilidade na loja."])
    return "\n".join(lines)
