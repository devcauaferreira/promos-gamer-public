# Auditoria do caminho de coleta e envio

O ciclo de cinco minutos agenda uma rodada; ele não garante que o catálogo
inteiro seja consultado nesse intervalo. A cobertura depende de tamanho do lote,
quantidade de produtos, descoberta, fontes acessíveis e duração real dos jobs.

## Correções aplicadas

- Retirada da instalação `playwright install --with-deps` de cada rodada: o setup
  valida o Chrome/Chromium pré-instalado no runner e desativa o download do Puppeteer.
  A auditoria encontrou mais de 12 minutos gastos em dependências do sistema,
  enquanto a coleta em si consumia cerca de 90 segundos.
- Lote dos sucessores configurável por `PROMOS_PRODUCT_LIMIT`, preservado também
  pela recuperação do watchdog. A descoberta pode ser renovada a cada 15 minutos.
- Produtos pausados e links já cobertos pelo cadastro manual não consomem vagas
  do rodízio. Ofertas verificáveis continuam recebendo prioridade sem excluir os
  produtos que aguardam há mais tempo.
- Falha ao revalidar um candidato impede sucesso do job de publicação e mantém
  a pendência visível. Resultado incerto do envio continua sem repetição automática.
- O monitor grava a política efetiva, fontes, cobertura, filas e etapas: coletado,
  disponível, histórico suficiente, desconto atingido, aprovado e enviado.
- A legenda informa quantos dias anteriores foram realmente observados. Janela
  de 30 dias não significa ter 30 dias completos de histórico.
- Verificação de conexão sem QR/mensagens e teste único com foto são modos separados.
  Testes de envio exigem autorização explícita e não simulam promoções aprovadas.

A biblioteca fixada `whatsapp-web.js 1.34.7` também contém a colisão de identidade
em mensagens com mídia corrigida no [PR oficial 201923](https://github.com/wwebjs/whatsapp-web.js/pull/201923).
O postinstall aplica esse backport de forma estrita e idempotente, preservando os
demais campos da mídia; versão ou bloco inesperado interrompe a preparação. A
reconciliação de um teste incerto consulta apenas o texto exato do teste no grupo
configurado. Encontrar uma mensagem com ACK pode confirmar a entrega sem reenvio;
não encontrá-la não autoriza uma nova tentativa automaticamente.

## O que é necessário para uma publicação

Uma oferta deve estar no cadastro ou ser descoberta numa fonte acessível. Precisa
de identidade/preço/pagamento confirmados, vendedor/entrega conforme as regras,
disponibilidade, histórico anterior comparável e queda de 25% sobre a média da janela
de 30 dias. A fila preserva a oferta exata; antes de enviar há nova coleta e nova
avaliação. Só a confirmação do servidor WhatsApp registra a publicação.

KaBuM pode publicar ofertas que cumpram esses critérios. Mercado Livre mantém
observações sem estoque confirmado em revisão. O modo público Amazon observado
também é de revisão. Magalu/Pichau não são fontes ativas enquanto faltar acesso
utilizável. Um job verde não significa cobertura das cinco lojas.

Cupons não validados não viram preço efetivo. A comparação usa a mesma oferta,
vendedor e pagamento. Não inclui preço riscado como prova de desconto. Uma oferta
que começa barata e permanece estável não passa por uma regra de queda histórica.

## Referências Python avaliadas

- [bernalli/price-tracker-bot: arquitetura](https://github.com/bernalli/price-tracker-bot/blob/62aac4f54d7125f994b77c5fdf432b68ce031e52/docs/architecture.md):
  separação de coleta, validação de anomalias, histórico e saúde. Referência útil
  para observabilidade; suas regras percentuais não são a nossa média de 30 dias.
- [sonoyumi/price-tracker: pipeline](https://github.com/sonoyumi/price-tracker/blob/75beb8aa09238c6228b9e3f7351e9f776246578f/src/price_tracker/tracker.py):
  decisão separada da coleta e referência à última leitura válida. Watchlist de
  URLs; os módulos examinados gravam preço antes de notificar, sem nossa outbox.
- [auhauhbr/rastreador-precos: serviço](https://github.com/auhauhbr/rastreador-precos/blob/026490c3152db8497ada8e4b4c4437806078248c/rastreador/servico.py#L117):
  projeto brasileiro de hardware com produto/oferta por loja e estatísticas de
  30/90 dias. Cadastro manual, não descoberta de todo o varejo; disponibilidade
  não é usada na decisão de alerta examinada.

Os códigos públicos mostram políticas mais amplas, como qualquer queda,
preço-alvo e novo mínimo. Isso não prova que grupos comerciais cumpram a nossa
regra. Não foi copiada uma arquitetura inteira, nem adotado fallback sem evidência.
