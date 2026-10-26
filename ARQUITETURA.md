# Fontes de dados e migração

A aplicação continua voltada a compartilhar promoções sem afiliação, sem frete
e sem acesso de escrita às lojas. Histórico, vendedores aprovados e publicação
no grupo permanecem separados da obtenção dos preços.

## Fluxo

`Fonte por loja → Offer padronizada → histórico por origem/condição/vendedor → regras → revalidação → WhatsApp`

Cada fonte implementa `status()`, `search(category, limit)` e `collect(entry)`.
`collectors/registry.py` escolhe o adaptador e cria o navegador somente se uma
fonte legada realmente precisar dele. Uma fonte sem acesso informa sua pendência,
sem tentar o site como alternativa. As demais continuam funcionando.

| Loja | Implementação atual | Dependência para funcionar |
| --- | --- | --- |
| Mercado Livre | `MercadoLivreSource`, catálogo oficial em revisão | OAuth válido; estoque por anúncio ainda não confirmado |
| Amazon | `AmazonSource`, importação de feed autorizado | Fornecedor/contrato e arquivo atualizado; integração nativa Creators API ainda não implementada |
| Magalu | `MagaluSource`, importação de feed autorizado | Fonte autorizada adequada a monitorar ofertas de terceiros |
| Pichau | `PichauSource`, importação de feed autorizado | Feed/parceria fornecido com autorização |
| KaBuM | `KabumSource`, navegador legado isolado | Página acessível; integração não oficial, sem comprovação de autorização da loja |

O modo KaBuM preserva o funcionamento existente durante a migração. Também pode
ser alterado para `authorized_feed` ou `disabled` em `settings.json`. Não é uma
API oficial. Nenhum módulo usa proxy rotativo, resolução de captcha ou técnicas
para contornar proteções.

## Mercado Livre primeiro

A documentação de [itens e buscas](https://developers.mercadolivre.com.br/pt_br/itens-e-buscas)
e de [consulta de produto](https://developers.mercadolivre.com.br/pt_br/produto-consulta-de-usuarios/publicacao-de-produtos)
documenta a autenticação Bearer e o recurso `GET /items/{item_id}`. O adaptador
consulta esse recurso e não usa endpoints de gestão, sugestões de preço, preços
B2B ou operações que pressupõem ser proprietário do anúncio.

Isso não garante que a aplicação tenha acesso a produtos de terceiros. Uma
resposta 403 suspende a fonte para revisão das permissões. O OAuth foi concluído
e o token foi aceito em `/users/me` e na consulta da aplicação. A leitura do
anúncio monitorado retornou `403 access_denied` no teste local e HTTP 403 no
GitHub Actions; a permissão de
acesso a anúncios terceiros deve ser validada separadamente da autenticação.

1. Obtenha acesso de uma aplicação cadastrada no Mercado Livre, conforme suas permissões.
2. Copie `.env.example` para `.env` e preencha `ML_ACCESS_TOKEN` localmente.
3. Execute `.\.venv\Scripts\python.exe main.py --check-source mercadolivre`.
4. Se houve 401/403, corrija o acesso e execute `main.py --reset-source mercadolivre`.

Tokens não devem ser colocados em `settings.json` nem enviados pelo chat.
O modo local com token estático não renova OAuth. Para GitHub Actions foi preparado
o modo `oauth_mode: supabase`, com callback HTTPS, state de uso único, PKCE e
renovação no servidor. O projeto Supabase e as funções HTTPS foram publicados;
e a aplicação Mercado Livre foi cadastrada/autorizada. Veja [DEPLOY.md](DEPLOY.md)
para a URL real e o atalho local `configurar-mercadolivre.cmd`.

O modo anterior de itens usa `item_ids` e continua disponível sem `api_resource`.
Ele permanece bloqueado e não é usado como fallback do catálogo. A configuração
atual seleciona explicitamente `api_resource: catalog`, com saúde e histórico
separados (`official_catalog` / `catalog_item_price`). Nenhum bloqueio anterior
é removido pela troca de recurso.

O teste real em 25/10/2026 confirmou HTTP 200 na busca, no produto `MLB19444510`
(Ryzen 5 5500) e em `/products/MLB19444510/items`, com 118 anúncios. O primeiro
resultado sem filtro de domínio era um computador completo, sem anúncios (404);
por isso não basta usar cegamente o primeiro resultado da busca.

`catalog_ids` aceita listas por categoria para produtos confirmados. Sem lista,
a descoberta consulta até três produtos por categoria e classifica seus títulos.
Cada lista de anúncios é limitada aos primeiros 100; um anúncio ausente dessa
página fica em revisão, sem presumir que tenha acabado. Links descobertos
preservam `catalog_id`, `item_id` selecionado e vendedor; links manuais antigos
precisam de mapeamento confirmado e não voltam ao endpoint bloqueado.

Na verificação limitada das cinco categorias, processadores e SSDs retornaram
anúncios utilizáveis pelo adaptador. Placas-mãe, RAM e fontes não produziram
entradas dentro dos três primeiros resultados classificados; isso não demonstra
ausência de ofertas na loja. A busca não promete cobertura completa do catálogo.

A resposta real não informou `status` nem `available_quantity` dos anúncios.
Segundo a documentação de publicação, `available_quantity` pode ser visível
somente para o proprietário do anúncio. O coletor também aceita evidência pelo
`buy_box_winner` documentado quando anúncio, vendedor, moeda e preço coincidem,
há quantidade positiva e a condição é nova, sem status/quantidade contraditórios.
No produto real testado, o winner veio nulo; essa alternativa ainda não liberou
as ofertas observadas.
Consequentemente, o coletor registra preço nos relatórios com `available=false`:
essas observações não entram no histórico de ofertas disponíveis nem são enviadas
ao grupo. Presença no catálogo e logística fulfillment não aprovam disponibilidade.
O preço vem de `price`, sem presumir PIX,
cupom ou desconto a partir de `original_price`. O chamado preparado inclui a
pergunta sobre uso permitido e como confirmar estoque por fonte oficial.
O vendedor é aprovado automaticamente quando o anúncio possui `official_store_id`
inteiro positivo, retornado pela fonte oficial, junto a um `seller_id` válido.
Não há cadastro manual de vendedores e `trusted_sellers` não contorna essa regra.
A descoberta já filtra anúncios sem loja oficial. O campo não comprova estoque.

Para Amazon, KaBuM, Magalu e Pichau, `seller_id` e `shipped_by` precisam identificar
a própria rede. Venda de parceiro com entrega pela rede é recusada. Na KaBuM,
o coletor confere o elemento “Vendido e entregue por:” contra o vendedor do produto;
sem essa evidência, deixa a oferta em revisão. Revalidação antes do envio inclui
quem entrega e a identificação da loja oficial.

## Por que não implementar quatro APIs presumidas

A [Creators API](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/onboarding/register-for-creators-api)
exige uma conta aprovada no programa de associados e outros critérios de
elegibilidade. Como o projeto não tem afiliação, ela não foi ativada nem apresentada
como solução imediatamente disponível. Se houver elegibilidade futura, o SDK
oficial poderá ser encapsulado em outro adaptador sem alterar os filtros.

O [portal Magalu](https://developers.magalu.com/) descreve OAuth e recursos de
catálogo, estoque e pedidos para integrações de sellers. Isso não comprova acesso
de leitura ao catálogo inteiro para divulgar promoções de terceiros. Por isso,
não usamos endpoints de administração de lojas para esse propósito.

Para Pichau não foi confirmada uma API pública adequada. O adaptador exige dados
de um fornecedor autorizado; não há feed real contratado/configurado.

## Contrato de feed

É um formato interno de importação, não o formato oficial de nenhuma loja.
O fornecedor ou um importador autorizado precisa gerar o JSON e mantê-lo atualizado.
Não existe download automático de um feed remoto nesta versão.

```json
{
  "schema_version": 1,
  "store": "pichau",
  "offers": [
    {
      "url": "https://www.pichau.com.br/ssd-exemplo-1tb",
      "title": "SSD exemplo 1TB",
      "seller_id": "Pichau",
      "shipped_by": "Pichau",
      "price_cents": 38000,
      "currency": "BRL",
      "available": true,
      "payment_terms": "À vista no PIX",
      "price_basis": "pix",
      "observed_at": "2026-10-25T03:00:00+00:00"
    }
  ]
}
```

O exemplo é fictício e não deve ser usado como oferta. `observed_at` precisa ser
o instante verdadeiro da observação, com fuso; arquivos expirados são recusados.
Configure `feed_path`, `authorization_reference` e `max_age_minutes` na loja.
`authorization_reference` identifica o contrato/permissão que você possui;
preencher esse campo não concede direitos nem verifica a autorização por si só.
O feed informa evidências (`seller_id`, `shipped_by` e, no Mercado Livre,
`official_store_id`), mas não pode fornecer um booleano de aprovação, alterar os
filtros ou fornecer o destino WhatsApp. `official_store_id` deve ser inteiro positivo
ou nulo; `shipped_by` deve ser texto, com a entidade responsável pela entrega.
Ausência da evidência impede aprovação automática. Quem gera o feed autorizado
deve preservar os dados reais da oferta, sem inferir entrega a partir do vendedor.

O caminho comum valida moeda BRL, centavos inteiros, título, vendedor, estoque,
data, URL da loja e identidade do produto. O histórico de API/feed usa uma chave
separada do histórico legado, evitando comparar preço PIX com outra base de preço.
O instante original do feed é preservado: reler um arquivo não fabrica dias de histórico.

## Diagnóstico e novas tentativas

`reports/http.jsonl` recebe status HTTP, URL sem credenciais/query, Content-Type,
Retry-After válido, tamanho/hash do corpo e códigos de erro de uma lista permitida.
Não registra Authorization, cookies, tokens, mensagens livres do servidor nem
corpo bruto, que podem conter dados pessoais. No navegador, usa a própria resposta
do Playwright, sem fazer uma consulta adicional para diagnosticar.

- 401 e 403: suspensão persistida em SQLite, sem tentativas automáticas recorrentes.
- 429: agenda a próxima tentativa, respeitando Retry-After, sem bloquear o trabalhador.
- 503 na API: até três tentativas com espera exponencial curta e variação; se houver
  Retry-After, agenda a próxima consulta. No navegador, agenda sem repetir a navegação.
- Falhas de rede e outros erros 5xx: nova tentativa adiada.
- Ausência de credencial/feed: nenhuma requisição externa da fonte.

`--reset-source LOJA` libera uma nova tentativa após corrigir a causa; não altera
credenciais ou permissões e não ignora os controles de acesso. Trocar o token cria
um novo contexto de saúde. Não compartilhe o banco nem relatórios com terceiros
sem revisar seus dados, como os identificadores públicos dos anúncios.

## Operação e verificação

Mensagens de ofertas aprovadas usam título, preço atual, média real dos sete dias
anteriores, percentual de queda e link direto da loja. Quando a KaBuM fornece
foto oficial correspondente ao produto, ela é enviada com a mensagem como legenda;
se a foto falhar antes do envio, segue apenas o texto. A imagem do exemplo de
terceiros não é reutilizada e o preço riscado anunciado não vira referência.
O agendamento do GitHub é configurado a cada cinco minutos, mas pode atrasar
ou perder eventos; confirme execuções com evento `schedule` na aba Actions.

Na nuvem, `.github/workflows/promos.yml` executa `cloud_run.py` uma vez por job.
O estado é persistido privadamente no Supabase antes e após envios. A conexão do
WhatsApp pode usar `whatsapp_cloud_job.py`: o job restaura a sessão RemoteAuth,
abre a ponte somente no loopback do próprio runner, verifica conexão/grupo e sessão
persistida, publica e salva a sessão antes de encerrar. Não acessa o loopback do PC.
O zip da sessão é dividido em partes cifradas com AES-256-GCM no cliente e fica em
bucket privado do Supabase. Um manifesto cifrado só é gravado após todas as partes,
preservando a sessão anterior se uma gravação falhar. A chave está nos secrets do
GitHub e no `.env` local, fora do bucket. Nenhuma sessão
ou QR é gravado em logs/artifacts. O QR fica cifrado temporariamente e só é exibido
por `conectar-whatsapp-cloud.cmd` no navegador local. A configuração inicial exige
ler um novo QR e validar restauração em outro job; ambos foram concluídos no projeto.
Jobs de conexão e monitor compartilham o mesmo grupo de concorrência. O agendamento
não mantém o WhatsApp conectado entre execuções e pode exigir nova autorização.
O histórico foi migrado e o monitor local foi encerrado. Coleta e publicação estão
ativadas no Actions a cada 5 minutos, somente para ofertas aprovadas. Cada coleta
verifica até 20 produtos descobertos em rodízio e só restaura a sessão WhatsApp
quando encontra uma oferta aprovada. O teste real
recebeu confirmação do servidor; envio sem ACK não é registrado como sucesso.

`main.py --sources` verifica configuração/saúde local sem acessar as lojas.
`main.py --check-source LOJA` verifica uma fonte isolada, sem publicar.
`main.py --discover` atualiza o cadastro apenas nas fontes disponíveis.
`main.py --watch --send` executa o monitor e publica somente ofertas aprovadas.
`reports/sources.json` contém a situação atual de cada fonte; `status.cmd` mostra
essas pendências junto à cobertura das categorias.

Os testes cobrem bloqueio persistido, limitação de requisições, Retry-After,
recuperação de 503, sigilo dos diagnósticos, transformação da API, falta de token,
validade do feed e o fluxo completo até um publicador simulado com deduplicação.
Uma simulação de envio não equivale a validar entrega real pelo WhatsApp.
