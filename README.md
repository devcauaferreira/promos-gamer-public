# Promos gamer — grupo do WhatsApp

O projeto está configurado no GitHub Actions para iniciar um ciclo a cada 5 minutos.
A sessão WhatsApp da nuvem foi conectada, salva com criptografia e restaurada em
outro runner; uma mensagem de teste recebeu confirmação do servidor. O computador
pode ficar desligado. Veja [DEPLOY.md](DEPLOY.md) para operação e reconexão.

As promoções só são enviadas quando houver histórico e desconto suficientes,
disponibilidade confirmada e vendedor dentro das regras. Hoje a KaBuM coleta;
Mercado Livre permanece limitado pela confirmação de disponibilidade, e Amazon,
Magalu e Pichau aguardam fontes autorizadas configuradas.

Monitor local de produtos reais, sem afiliados e sem cálculo de frete.

Para GitHub Actions e OAuth HTTPS do Mercado Livre, consulte [DEPLOY.md](DEPLOY.md).
O código e os workflows podem ser públicos; credenciais e configurações da instalação
ficam nos Secrets do GitHub e no Supabase privado.
As funções e migrações Supabase foram publicadas e tiveram autenticação/RLS verificadas.
O OAuth do Mercado Livre foi concluído; o token foi validado. A consulta ao anúncio
monitorado ainda exige resolver a resposta `403 access_denied` da API.

## Estado atual

As fontes são selecionadas por loja em `settings.json`. A KaBuM mantém a busca
web legada para processador, placa-mãe, memória RAM, SSD, fonte, placa de vídeo e
kit upgrade. O Mercado Livre usa o catálogo oficial com OAuth conectado, mas
continua sem confirmação de disponibilidade dos anúncios consultados. Amazon,
Magalu e Pichau aguardam feeds autorizados. Não há tentativa de voltar aos sites
bloqueados quando uma API ou feed está sem acesso.

A integração nativa com a Creators API da Amazon ainda não foi implementada,
pois depende de elegibilidade no programa de associados, que este projeto não tem.
O cadastro de uma loja não significa que sua fonte esteja operacional.
Consulte [ARQUITETURA.md](ARQUITETURA.md) para as decisões, documentação oficial,
configuração do Mercado Livre e contrato de feed.

A descoberta lê até 20 produtos por categoria/loja a cada seis horas e mantém
um cadastro em SQLite. Consulta até 20 produtos descobertos por ciclo, além dos
links manuais, com rodízio dos
menos recentemente verificados. A cobertura depende das fontes configuradas;
não há garantia de encontrar todas as promoções de todos os catálogos. Catálogos
não atualizados por sete dias deixam de entrar na fila. Links cadastrados à mão
continuam sendo verificados somente pela fonte selecionada para sua loja.

## Executar neste computador

As dependências foram instaladas em `.venv` e `node_modules`.

- `coletar-precos.cmd`: consulta os links uma vez, sem publicar.
- `monitorar.cmd`: coleta a cada 5 minutos, sem publicar. Mantenha o terminal aberto.
- `buscar-produtos.cmd`: atualiza as categorias nas fontes disponíveis, sem publicar.
- `status.cmd`: mostra a cobertura e as falhas de descoberta por loja e categoria.
- `conectar-whatsapp.cmd`: exibe o QR Code e permite escolher um grupo.
- `selecionar-grupo.cmd`: lista os grupos da sessão conectada para escolher pelo número.
- `publicar-ofertas.cmd`: coleta periodicamente e envia somente ofertas aprovadas.
  Mantenha também a ponte do WhatsApp aberta.

Primeiro crie o grupo pelo WhatsApp no celular. Abra `conectar-whatsapp.cmd`, entre
em **Aparelhos conectados → Conectar aparelho** e leia o QR Code. Depois escolha
o número do grupo no terminal; o ID será salvo em `settings.json`.
Nenhum envio acontece apenas ao conectar. A conta precisa poder enviar mensagens
no grupo escolhido. O programa não cria grupos nem adiciona pessoas.

## Cadastrar outros produtos

```powershell
.\.venv\Scripts\python.exe main.py --add "LINK_DIRETO_DO_PRODUTO"
.\.venv\Scripts\python.exe main.py --collect
.\.venv\Scripts\python.exe main.py --groups
```

Use links completos da loja, sem encurtadores. Confira variante e vendedor.
O link é consultado pela fonte da loja. A KaBuM lê pagamento da página; APIs e feeds
informam sua própria base de preço. A aprovação do vendedor é automática:
no Mercado Livre, exige `official_store_id` inteiro positivo vindo da API/feed
autorizado e `seller_id` válido. Sem loja oficial, o anúncio não passa.
Na Amazon, KaBuM, Magalu e Pichau, exige venda e entrega pela própria rede.
Vendido por parceiro e entregue pela Amazon/KaBuM não passa. O feed deve informar
`shipped_by`; sua ausência deixa a oferta pendente. Na KaBuM, a entrega é lida
do elemento “Vendido e entregue por:” e precisa corresponder ao vendedor do produto.
Não é necessário cadastrar vendedores. A antiga lista `trusted_sellers` permanece
compatível na configuração, mas não substitui essas regras das cinco lojas.
A reputação e as avaliações do produto não são usadas como reputação do vendedor.
Anúncios sem identificação do vendedor ficam pendentes.

## Quando publica

Exige ao menos um dia anterior de histórico e queda mínima de 15% sobre a média
dos últimos 30 dias. O dia atual não entra na média. Não usa preço riscado.
Guarda uma observação diária em UTC por produto, vendedor e condição de pagamento.
Sem histórico, com estoque ausente ou dados incompletos, aguarda revisão.
Repetições são bloqueadas por 24 horas por oferta/grupo, com limite de dez
mensagens por execução. As ofertas aprovadas são ordenadas pela maior queda
sobre a média; excedentes são reavaliados no próximo ciclo. O anúncio é coletado
novamente antes de enviar para verificar preço, vendedor, estoque e pagamento.
Não há envio imediato só porque uma loja anuncia desconto.
As mensagens informam que o frete não está incluído.

`reports/latest.json` mostra preços, mensagens previstas, motivos de revisão e erros
da última consulta. SQLite em `database/promos.sqlite3` guarda histórico e envios.
`reports/discovery.json` mostra a cobertura por loja/categoria e a data da busca,
incluindo buscas em cache. `reports/sources.json` mostra pendências de acesso.
`reports/http.jsonl` guarda diagnósticos HTTP sem corpo bruto, cookies ou tokens.
Respostas 401/403 suspendem a fonte até corrigir acesso; 429/503 adiam tentativas.
Use `main.py --reset-source LOJA` após corrigir a causa. As demais lojas continuam.
Ainda não existe interface de revisão manual nem aprovação forçada.

Uma tentativa com resposta incerta fica bloqueada em `dispatches` (`sending` ou
`uncertain`) para evitar duplicação. Confira o grupo e o registro no banco antes
de resolver esse estado manualmente. O retorno de `sendMessage` identifica a
mensagem; não confirma leitura ou entrega a todos os integrantes.

## Conexão do WhatsApp

Usa whatsapp-web.js, uma integração não oficial via WhatsApp Web. A própria biblioteca
[avisa que há risco de bloqueio da conta](https://docs.wwebjs.dev/).
A sessão e o grupo de destino são configurados privadamente por instalação.
Ainda não foi validada a entrega de uma oferta real aprovada pelo histórico.
A ponte escuta apenas `127.0.0.1:8787`, exige um token local gerado automaticamente
em `.bridge_token` e aceita envio apenas ao grupo configurado. Sessão, token,
configuração e banco ficam fora do Git. Não compartilhe `.wwebjs_auth` ou o token.

## Instalação em outro computador

Requer Python 3.10+ e Node.js 18+:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
npm.cmd ci
Copy-Item settings.example.json settings.json
```

Copie também o cadastro de produtos. A demonstração fictícia continua disponível
com `main.py --demo`, isolada do banco real.

Para configurar a API, copie `.env.example` para `.env` e preencha o token localmente.
Valide apenas o Mercado Livre com `main.py --check-source mercadolivre`.
`main.py --sources` mostra as pendências sem acessar nenhuma loja.

## Verificação

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check publishers/whatsapp_bridge.cjs
```
