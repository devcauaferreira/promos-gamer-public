# Revisão do price-alert-bot

Referência: [CaioMassola/price-alert-bot](https://github.com/CaioMassola/price-alert-bot),
consultado em 25/10/2026. O projeto é um serviço Java/PostgreSQL contínuo com
alertas no Discord. O Promos Gamer usa jobs efêmeros no GitHub Actions, estado
privado no Supabase e envio para um grupo do WhatsApp.

| Prática observada | Decisão para o Promos Gamer |
| --- | --- |
| `/products/search`, `/products/{id}` e `/products/{id}/items` no Mercado Livre | Já implementada. Preserva o ID do anúncio e do vendedor; a busca geral com 403 não é usada como fallback. |
| Excluir usados e anúncios com compra mínima acima de uma unidade | Aplicada também à descoberta e à coleta do catálogo. |
| Histórico por preço alterado e amostra diária | Mantemos uma amostra por dia anterior para que o job de cinco minutos não distorça a média dos sete dias. |
| Referência de preço anunciado quando o histórico ainda é curto | Não adotada: o usuário pediu queda real de 15% sobre histórico. O preço riscado da loja não aprova publicação. |
| Tratar a presença em `/products/{id}/items` como oferta disponível | Não adotada para publicação automática. A lista traz preços reais, mas não confirma estoque do anúncio testado. `available_quantity` pode ser restrito ao proprietário. |
| Revalidar oferta, reservar envio antes da chamada externa e marcar entrega incerta | Já implementado no fluxo do WhatsApp; falhas ambíguas não geram reenvio automático. |
| Renovar OAuth e persistir tokens | Já implementado na função privada do Supabase. |
| Workers separados para coleta e entrega | O workflow separa a coleta do início da sessão WhatsApp; esta só inicia quando há candidato aprovado. |
| Alerta persistido entre coleta e entrega | Foi corrigida a passagem entre etapas: `pending_offers` preserva o anúncio exato e o preço aprovado. O publicador consome a fila com validade de 30 minutos e revalidação, em vez de coletar outro lote do rodízio. |
| Serviço sempre ligado com `fixedDelay` | Não cabe diretamente no GitHub Actions. O cron do GitHub está configurado, mas ainda não houve evento `schedule` observado. Para cadência garantida, seria necessário outro disparador ou serviço persistente. |
| Amazon declarada pendente | Mesma conclusão aqui. Credenciais de comprador não habilitam a Creators API; Magalu e Pichau também aguardam fontes autorizadas. |

O repositório de referência [relata preços reais do catálogo](https://github.com/CaioMassola/price-alert-bot/blob/main/docs/MERCADO-LIVRE-DIAGNOSTICO.md),
mas declara que o envio de um alerta do Mercado Livre ainda não foi validado.
O código marca como disponível todo item listado no recurso de competição.
Esse comportamento não prova estoque no momento do envio. A
[documentação do Mercado Livre](https://developers.mercadolivre.com.br/pt_br/autenticacao-e-autorizacao/publicacao-de-produtos)
explica que `available_quantity` de um anúncio pode ser visível apenas com o
token do proprietário. Manter os anúncios de catálogo em revisão evita afirmar
uma promoção que o comprador talvez não consiga adquirir.

Antes de habilitar publicação automática do catálogo, confirmar uma fonte
autorizada e verificável de disponibilidade, condição de venda e link que abre
o anúncio exato; então testar um único anúncio e sua revalidação. Para as demais
lojas, conectar feeds/autorização reais e testar venda e entrega pela própria loja.

Verificação operacional em 25/10: cinco ciclos manuais concluídos, nenhum evento
`schedule` observado. As evidências validam execução manual e persistência,
mas ainda não confirmam operação autônoma a cada cinco minutos. O resumo de cada
novo ciclo fica em `monitor_runs`; `python status-cloud.py` mostra o último resultado
sem divulgar grupo, credenciais ou links privados.
