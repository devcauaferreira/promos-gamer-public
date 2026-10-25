# Consulta técnica: acesso a anúncios públicos de terceiros

Modelo para preencher privadamente e copiar no canal de suporte do DevCenter.
Não foi enviado automaticamente. Não inclua Client Secret, access token, refresh
token, códigos OAuth ou o cabeçalho Authorization no chamado.

## Assunto

OAuth válido, mas leitura de anúncio e busca pública retornam HTTP 403

## Descrição sugerida

Aplicação: PREENCHER_PRIVADAMENTE

APP ID: APP_ID

Site: MLB / Brasil

Data dos testes: 25/10/2026

Objetivo: acompanhar preços e disponibilidade de componentes de informática
vendidos por terceiros e divulgar boas ofertas em um grupo, sem afiliação e sem
administrar contas de vendedores, vendas, mensagens ou publicações.

O fluxo OAuth authorization_code foi concluído, com state, PKCE S256 e renovação
offline configurados. O token é aceito nos seguintes recursos:

- `GET /users/me`: HTTP 200.
- `GET /applications/APP_ID`: HTTP 200.

Os seguintes recursos foram recusados:

- `GET /items/MLB5391978169`: HTTP 403, `error=access_denied`.
- `GET /sites/MLB/search?q=ryzen%205%205500&limit=1`: HTTP 403, `error=forbidden`.

Teste alternativo de catálogo realizado na mesma data, com o mesmo OAuth:

- `GET /products/search?status=active&site_id=MLB&q=ryzen%205%205500&domain_id=MLB-COMPUTER_PROCESSORS&limit=5`: HTTP 200.
- `GET /products/MLB19444510`: HTTP 200; Ryzen 5 5500 ativo.
- `GET /products/MLB19444510/items?limit=5`: HTTP 200; 118 anúncios no total,
  com preços, moeda e identificadores de vendedores. O adaptador também validou
  a página com `limit=100`. A resposta não informou `status` nem `available_quantity`
  dos anúncios; `buy_box_winner` do produto era nulo.
- O primeiro resultado da busca sem domínio era um computador completo
  (`MLB49199183`), cujo recurso `/items` retornou 404. Isso não foi interpretado
  como negação geral de acesso ao catálogo.

O catálogo está acessível tecnicamente, mas ainda precisamos confirmar se esta
finalidade de monitoramento é permitida e como validar estoque/atividade de cada
anúncio sem depender do recurso `/items/{item_id}` recusado. Até essa confirmação,
as ofertas de catálogo ficam em revisão e não alimentam o histórico de preços
disponíveis nem são publicadas automaticamente.

A consulta ao anúncio foi testada no computador e em um runner do GitHub Actions,
com HTTP 403 nos dois ambientes. Todas as consultas utilizaram HTTPS e Bearer token.
Não houve uso de proxy, alteração de identidade do cliente para evitar controles
ou repetição automática das requisições negadas.

Estado verificado da aplicação:

- `active=true`, `blocked=false`, `disabled=false`.
- Bloqueio parcial: `blocked=false`.
- `use_pkce=true`.
- Fluxos permitidos: `authorization_code` e `refresh_token`.
- Scopes retornados: `read`, `write`, `offline_access`; o monitor usa apenas GET
  nos recursos de dados e não realiza escritas no marketplace.
- `sandbox_mode=true`, `certification_status=not_certified`. Não foi presumido
  que esses campos sejam a causa do erro; solicitamos esclarecimento sobre sua relevância.
- A conta autorizada está ativa, com e-mail confirmado e sem `required_action` pendente.

Solicitamos esclarecer:

1. Esta finalidade pode usar a API para leitura de anúncios e preços de vendedores
   que não autorizaram individualmente a aplicação? Qual recurso documentado é adequado?
2. Há permissão funcional, requisito de validação/homologação, restrição de IP ou
   política de acesso pendente para esta aplicação? Qual é a correção específica?
3. Os campos `sandbox_mode` e `certification_status` restringem estes recursos?
   Se sim, qual é o procedimento oficial para este tipo de aplicação?
4. Caso a API de integração de sellers não permita esta finalidade, existe feed,
   programa ou fonte de dados oficialmente autorizada para monitoramento de ofertas?
5. O acesso observado a `/products/{id}/items` pode ser usado para esta finalidade?
   Como confirmar disponibilidade e condição de pagamento de cada anúncio retornado?

A documentação de publicação informa que `available_quantity` pode ser restrita
ao token proprietário. Não solicitamos acesso a estoque privado de terceiros;
precisamos de um indicador público de disponibilidade para o comprador. O coletor
já aceita `buy_box_winner` com estoque positivo e identidade/preço coincidentes,
mas o produto real consultado retornou esse campo nulo.

## Referências

- [Erro 403](https://developers.mercadolivre.com.br/pt_br/autenticacao-e-autorizacao/erro-403)
- [Permissões funcionais](https://developers.mercadolivre.com.br/pt_br/permissoes-funcionais)
- [Quantidade disponível](https://developers.mercadolivre.com.br/pt_br/autenticacao-e-autorizacao/publicacao-de-produtos)
- [Competição e buy_box_winner](https://developers.mercadolivre.com.br/en_us/catalog-competition)
- [Suporte para integradores](https://developers.mercadolivre.com.br/pt_br/envio-de-produto/suporte-para-integradores)

Após uma correção efetiva de acesso, faça um único teste controlado antes de
reativar a coleta. Não aumente permissões de escrita como tentativa de corrigir
uma consulta GET. Mantenha o endpoint de itens suspenso. O catálogo pode ser
consultado no modo explícito de revisão, sem publicação automática enquanto faltar
disponibilidade confirmada.
