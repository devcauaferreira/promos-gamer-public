def money(cents):
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_message(offer, decision):
    from services.niche import CATEGORIES, category_for
    category = category_for(offer.title)
    lines = ([CATEGORIES[category]] if category else []) + [offer.title,
             f"Loja: {offer.store} | Vendedor: {offer.seller_id}",
             f"Preço: {money(offer.price_cents)}"]
    lines.append("Frete não incluído. Consulte a entrega na loja.")
    lines.append(f"Pagamento: {offer.payment_terms}")
    if decision.average_cents is not None:
        lines.extend([f"Média histórica do produto: {money(decision.average_cents)}",
                      f"Queda sobre a média: {decision.discount_percent:.1f}%".replace(".", ",")])
    lines.append("Preço e disponibilidade podem mudar. Confira antes de comprar.")
    lines.append(offer.affiliate_url)
    return "\n".join(lines)
