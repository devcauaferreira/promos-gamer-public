# GitHub Actions + callback HTTPS do Mercado Livre

O código pode ficar em um repositório público. Credenciais, identificadores da
instalação, grupo WhatsApp e cadastro privado ficam nos Secrets do Actions;
banco, tokens OAuth e sessão cifrada permanecem no Supabase privado.

O workflow agenda um ciclo a cada cinco minutos, sujeito a atrasos do GitHub.
Cada rodada consulta até 20 produtos descobertos em rodízio, além dos links
manuais. A sessão WhatsApp só é iniciada quando a coleta encontra oferta aprovada.

A URL de callback é configurada em `ML_REDIRECT_URI`, nos secrets da função:
`https://PROJECT_REF.supabase.co/functions/v1/mercadolivre-callback`.
Consulte a URL real no seu painel Supabase ou execute localmente
`configurar-mercadolivre.cmd`. Não registre os valores reais nesta documentação.

O repositório público começa com histórico novo. O histórico anterior, seus logs
e os documentos da instalação permanecem no repositório privado de backup, com
os workflows desativados. Apenas o repositório público executa o monitor.

## Componentes

1. GitHub Actions executa `cloud_run.py` uma vez por agendamento, não `--watch`.
2. Supabase Edge Function `mercadolivre-callback` recebe o redirecionamento HTTPS,
   valida state de uso único e PKCE, troca o código e renova os tokens.
3. Tokens e verificadores são cifrados com AES-256-GCM. A chave fica nos secrets
   das funções, separada das tabelas. O GitHub recebe apenas access token por um
   endpoint protegido; client secret e refresh token permanecem no Supabase.
4. `promos-state` persiste um snapshot privado/versionado do SQLite. Reservas de
   envio são gravadas remotamente antes da chamada ao WhatsApp, para que a morte
   do runner não provoque reenvio automático. Conflito de versão interrompe a gravação.
5. `whatsapp_cloud_job.py` inicia uma ponte dentro do job. RemoteAuth restaura e
   salva a sessão cifrada em bucket privado do Supabase. A ponte do computador
   permanece independente; o job não depende dela nem a expõe na internet.

Cada [runner hospedado](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners)
é uma máquina temporária; não serve como endereço HTTPS permanente. O agendamento
do Actions pode atrasar. Não há promessa de execução exata a cada 5 minutos ou
de disponibilidade contínua. Os runners padrão usados aqui são gratuitos para
repositórios públicos, conforme a [cobrança do GitHub Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
Isso não inclui runners maiores ou serviços externos pagos.

## Recursos necessários para publicar

- Repositório público com código revisado e configurações em Secrets.
- Projeto Supabase sugerido: `promos-gamer`, em uma organização do usuário.
- Aplicação de desenvolvedor no Mercado Livre, com permissões adequadas e PKCE S256 habilitado.
- Para envio pelo Actions: sessão WhatsApp da nuvem conectada por QR, salva e
  restaurada com sucesso em outro job, e grupo encontrado nessa sessão.

Não é necessário comprar domínio nem instalar Cloudflare Tunnel: o endereço da
Edge Function será `https://PROJECT_REF.supabase.co/functions/v1/mercadolivre-callback`.
`PROJECT_REF` será obtido somente após criar o projeto. Este endereço é um modelo.

## Preparar e publicar o Supabase

Depois que a conta estiver conectada e o projeto criado:

1. Aplicar `supabase/migrations/202610250001_cloud.sql` no projeto.
2. Cadastrar os secrets abaixo no painel de Edge Functions ou pela CLI oficial.
3. Publicar `mercadolivre-callback` e `promos-state`, respeitando `supabase/config.toml`.

```text
BOT_API_SECRET                segredo aleatório com pelo menos 32 caracteres
ML_CLIENT_ID                  APP ID da aplicação Mercado Livre
ML_CLIENT_SECRET              Client Secret da aplicação
ML_REDIRECT_URI               URL HTTPS exata da função, sem /start ou query string
ML_TOKEN_ENCRYPTION_KEY        32 bytes aleatórios codificados em base64
```

Não cole valores desses secrets no código ou no chat. O Supabase fornece
`SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` ao runtime da função. As tabelas têm
RLS e nenhum acesso concedido a `anon` ou `authenticated`.

Exemplo de publicação pela [CLI oficial](https://supabase.com/docs/guides/functions/deploy),
depois de autenticar e vincular o projeto:

```text
supabase link --project-ref PROJECT_REF
supabase db push
supabase functions deploy mercadolivre-callback
supabase functions deploy promos-state
```

As funções usam `verify_jwt=false` porque o callback externo não envia JWT
Supabase. Isso **não** elimina a autenticação da aplicação: `/start`, `/status`,
`/token` e `promos-state` exigem `BOT_API_SECRET`; o callback público exige state
válido, não expirado e ainda não consumido. Não há endpoint público de tokens.
Não publique apenas um callback sem essas validações.

## Autorizar o Mercado Livre

A [documentação de OAuth](https://developers.mercadolivre.com.br/autenticacao-e-autorizacao)
exige correspondência exata do redirect e descreve PKCE e refresh tokens de uso único.

1. Cadastre a URL publicada em **URIs de redirect** da aplicação Mercado Livre.
2. Configure localmente no `.env` `SUPABASE_PROJECT_URL` e `BOT_API_SECRET`.
3. Execute `python autorizar-mercadolivre.py start` e abra o link privado gerado.
4. Entre na sua conta e autorize a aplicação. O state expira em dez minutos.
5. Execute `python autorizar-mercadolivre.py status` para confirmar a conexão.

Neste computador, `configurar-mercadolivre.cmd` recebe APP ID e Client Secret
em terminal local, cadastra os secrets na função e abre o fluxo oficial de
autorização. O Client Secret não aparece na tela nem é enviado pelo chat.

O código e os tokens não são mostrados na página de sucesso. A função também não
os imprime em logs; a infraestrutura do provedor ainda pode registrar metadados
HTTP, portanto restrinja o acesso aos logs do projeto.

O callback registra somente etapa, código de erro controlado e status HTTP em
`ml_oauth_diagnostics`, tabela privada com RLS. `autorizar-mercadolivre.py status`
mostra a última falha segura. `invalid_client` indica que o provedor não aceitou
o par APP ID/Client Secret; confira as credenciais da mesma aplicação e execute
novamente o configurador. `offline_access_missing` indica ausência de refresh
token. O link solicita explicitamente `read offline_access`. Uma tentativa que
consumiu o state exige um link novo, não recarregar o callback antigo.

Se o refresh ficar incerto após timeout ou falha de persistência, a função mantém
um bloqueio para não reutilizar um refresh token possivelmente consumido. Verifique
o estado e refaça a autorização com `start` quando necessário. Tokens novos são
gravados condicionalmente para evitar colisão entre uma renovação e outra autorização.
Reautorizar também consome um state novo. Não há repetição automática do POST OAuth.

Autenticar a aplicação não garante permissão para consultar todos os anúncios de
terceiros, nem ativa busca global. O adaptador continua limitado aos IDs conhecidos.
Amazon, Magalu e Pichau continuam dependendo de fontes autorizadas próprias.

## Configurar o GitHub

O workflow `.github/workflows/promos.yml` agenda um ciclo a cada 5 minutos,
começando no minuto 3 de cada hora UTC. Possui disparo manual, limite de 25 minutos
e concorrência única.
Ele não faz commits de banco, tokens ou relatórios no repositório.

Cadastre em **Settings → Secrets and variables → Actions → Secrets**:

| Secret | Conteúdo |
| --- | --- |
| `SUPABASE_PROJECT_URL` | URL pública do projeto Supabase |
| `BOT_API_SECRET` | Mesmo segredo privado usado pelas funções |
| `PROMOS_SETTINGS_JSON` | Conteúdo ajustado de `settings.cloud.example.json`, com grupo e fontes de dados |
| `PROMOS_PRODUCTS_JSON` | Opcional: cadastro inicial de links em JSON |
| `WHATSAPP_BRIDGE_URL` | Apenas para envio: URL base HTTPS da ponte externa |
| `WHATSAPP_BRIDGE_TOKEN` | Apenas para envio: token da ponte |
| `WHATSAPP_SESSION_KEY` | Chave AES de 32 bytes em base64, para RemoteAuth no próprio runner; já cadastrada |

O modo OAuth em `sources.mercadolivre` deve ser `"oauth_mode": "supabase"`.
Não precisa copiar access/refresh tokens manualmente para o GitHub.
A variável Actions `PROMOS_CLOUD_ENABLED=true` libera o job após configurar os
recursos e secrets. Enquanto estiver ausente, o monitor da nuvem fica desativado.
A opção `publish` do disparo manual começa desativada. Para permitir publicação
nos agendamentos, crie a variável Actions `ENABLE_WHATSAPP_PUBLISH=true`, somente
depois de configurar e verificar a ponte e o grupo.

## Preservar o histórico já coletado

Antes da primeira execução do Actions, pare o monitor local para evitar dois
produtores independentes no mesmo grupo. Com as funções publicadas e secrets
locais configurados, execute:

```text
python migrar-historico-cloud.py
```

Ele inicializa apenas um estado remoto vazio. Nunca sobrescreve um histórico
remoto já existente. Depois, os jobs restauram e atualizam esse estado. Não use
cache/artifact do Actions como único banco de preços ou registro de envios.
O snapshot tem limite de 5 MB; ao atingir esse tamanho, a execução interrompe
para migrar o armazenamento. Não use dois repositórios/workflows independentes
como produtores concorrentes. A versão protege contra gravação de snapshots antigos.

Para reativar uma fonte suspensa na nuvem, será necessário restaurar o snapshot,
corrigir o acesso e persistir a liberação no mesmo estado remoto. O reset do banco
local independente não altera a suspensão guardada na nuvem.

## WhatsApp no runner

O modo atual abre e fecha o WhatsApp dentro de cada job, usando a estratégia
[RemoteAuth da biblioteca](https://wwebjs.dev/guide/creating-your-bot/authentication.html).
O armazenamento `promos-whatsapp-private` é privado e recebe apenas zip cifrado
com AES-256-GCM. `whatsapp-session` exige BOT_API_SECRET e não recebe a chave da
cifra. A chave nunca vai para o bucket. Não há exposição pública da ponte nem
necessidade de comprar domínio ou hospedar um serviço de WhatsApp permanente.

1. Execute o workflow **Conectar WhatsApp na nuvem** e abra `conectar-whatsapp-cloud.cmd`.
2. No celular, leia o QR em **Aparelhos conectados → Conectar aparelho**.
3. Aguarde o job confirmar **Sessão da nuvem conectada e persistida**. A biblioteca
   precisa de cerca de um minuto após conectar para salvar a primeira sessão.
4. Execute novamente esse workflow: ele precisa restaurar a sessão sem novo QR.
5. Só depois habilite publicação no agendamento e desligue o monitor local, para
   evitar dois históricos independentes e duplicação de publicações.

O visualizador do QR é um servidor temporário no loopback do PC com caminho
aleatório. O QR é cifrado antes de ser enviado ao Supabase, expira em 60 segundos
no visualizador e é removido após conexão/encerramento. Nunca é publicado em
artifacts/logs. O usuário precisa manter o visualizador aberto durante a leitura.
Se a sessão expirar, o job de monitor falha sem imprimir QR; repita a conexão manual.
O runner não fica ligado entre agendamentos. Restauração e envio com confirmação
do servidor foram validados durante a configura??o da instala??o. Uma leitura nova só é necessária se a
sessão expirar ou for desconectada no WhatsApp.

A ponte aguarda 15 segundos de estabilidade após conectar e exige ACK do servidor
antes de devolver sucesso. A versão fixada da biblioteca usa uma compatibilidade
de MsgKey baseada no [PR upstream 201901](https://github.com/wwebjs/whatsapp-web.js/pull/201901).
Resultados incertos permanecem reservados, sem reenvio automático. O modo de teste
tem reserva própria; uma nova tentativa após resultado incerto exige autorização
explícita e preservação do registro anterior.

### Alternativa com ponte externa

O Actions não acessa `127.0.0.1:8787` do seu computador. Para publicar, a ponte
externa precisa ter sessão persistente e aceitar:

```text
POST https://SUA-PONTE/send
Authorization: Bearer SEGREDO_DA_PONTE
Content-Type: application/json

{"group_id":"ID_DO_GRUPO@g.us","message":"Texto da oferta"}
```

Resposta de sucesso: `{"message_id":"identificador"}`. O cliente não segue
redirecionamentos nem repete envios automaticamente. A ponte deve validar o grupo
permitido e proteger a sessão. O código local `whatsapp_bridge.cjs` não foi
transformado em serviço público e não deve ser exposto diretamente na internet.
Para mantê-lo local, outra alternativa é um runner self-hosted no computador;
nesse caso, o computador continua necessário e não é hospedagem pelo GitHub.

## Validação desta entrega

Testes Python verificam persistência/restauração do estado, reserva antes de envio,
restrição de HTTPS e compatibilidade dos filtros. Testes Node verificam state,
PKCE, autenticação das rotas administrativas e cifra autenticada.
Banco, RLS, autenticação das funções, publicação HTTPS e um ciclo real no Actions
foram validados nas contas conectadas. OAuth com a aplicação real do Mercado Livre
foi concluído. A conexão/restauração RemoteAuth e o envio real com ACK foram
confirmados em um runner independente. Os testes locais também cobrem cifra,
diretório ausente em runner novo, compatibilidade de IDs e falta de confirmação.

## Cuidados da versão pública

- Não versionar `.env`, `settings.json`, `products.json`, banco, relatórios,
  certificados, QR ou diretórios de sessão. `.gitignore` exclui esses arquivos.
- Os workflows com credenciais aceitam somente agendamento ou disparo manual.
  Pull requests executam apenas os testes, sem secrets de produção.
- Actions de terceiros ficam fixadas por SHA e checkout não persiste credenciais.
- `services.public_job` guarda stdout/stderr das tarefas somente em arquivo
  temporário dentro do runner. Não envia esse arquivo para artifacts ou caches.
  O log público informa sucesso/falha; diagnósticos detalhados exigem ambiente privado.
- O job de segurança verifica segredos no histórico e arquivos privados rastreados.
  Uma falha bloqueia a CI, mas não remove um segredo já enviado: se isso ocorrer,
  revogue a credencial e remova o conteúdo antes de voltar a publicar.
- O nome do proprietário, o nome do repositório, o código e os logs resumidos
  do Actions são públicos. GitHub Secrets não tornam esses metadados privados.
