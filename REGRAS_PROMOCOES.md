# Comparação das regras de alertas

Revisão de código público em 26/10/2026. Não existe uma regra universal de 15%.
Os exemplos abaixo descrevem implementações e padrões de configuração; não
comprovam a frequência de alertas nem as regras internas de bots comerciais.

| Projeto | Critério encontrado |
| --- | --- |
| [CaioMassola/price-alert-bot](https://github.com/CaioMassola/price-alert-bot/blob/d712dd19ac9808046da9962bb5e8ea0306db1bb7/src/main/java/com/pricealert/service/DiscountService.java) | Descoberta: padrão de 25% abaixo da média de 30 dias, com maturidade mínima. Produtos acompanhados também têm preço-alvo, novo mínimo e queda de 10% sobre o preço anterior. |
| [bernalli/price-tracker-bot](https://github.com/bernalli/price-tracker-bot/blob/62aac4f54d7125f994b77c5fdf432b68ce031e52/src/price_tracker/core/alert.py#L239) | Percentual configurável sobre o último preço, redução em reais, qualquer queda ou preço-alvo. |
| [andrewschultzw/price-tracker](https://github.com/andrewschultzw/price-tracker/blob/45195579ceb3ac13b785e52d9cab5d39f4c07d3e/server/src/stats/price-stats.ts#L43) | Preço-alvo e novos mínimos de 30/90 dias ou de todo o histórico, com cobertura mínima e confirmação de leituras suspeitas. |

O projeto de Caio também possui fallback baseado no preço original anunciado
pela loja quando falta histórico, rotulado `STORE_DISCOUNT_UNVERIFIED`. Isso é
menos rigoroso que nossa regra e não foi adotado. Os padrões de 25% e 10% estão
na [configuração](https://github.com/CaioMassola/price-alert-bot/blob/d712dd19ac9808046da9962bb5e8ea0306db1bb7/src/main/resources/application.yml#L45).

Nossa configuração permanece em 15% sobre a média dos sete dias UTC anteriores,
com pelo menos um dia anterior e uma amostra diária por produto/vendedor/pagamento.
É uma escolha de curadoria, não um requisito técnico. Uma queda menor pode ser
útil ao comprador, mas isso não a faz cumprir o critério atualmente escolhido.

Há uma limitação: com um único dia anterior, a média representa apenas esse dia,
mesmo que a janela permitida seja de sete dias. A confiança aumenta conforme o
histórico ganha cobertura. Um percentual fixo também não detecta um produto que
já começou barato e permaneceu nesse preço.

Minha avaliação é preservar os 15% conforme a decisão atual e medir a frequência
de alertas. Uma evolução possível é acrescentar preços-alvo por modelo e novos
mínimos, com rótulos distintos e histórico suficiente. Esses critérios não foram
ativados. Diminuir o percentual não corrige fontes bloqueadas ou estoque não
confirmado e não produziria alertas na comparação auditada em que nenhum preço caiu.
