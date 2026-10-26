# Hospedagem automática do Promos Gamer

**Decisão posterior do usuário:** continuar no GitHub Actions. Foi implementado
encadeamento com token temporário do próprio job, controle de intervalo e
variáveis de interrupção. A operação está descrita em [DEPLOY.md](DEPLOY.md).
A análise abaixo preserva as recomendações e limitações pesquisadas; não foi
contratado outro provedor e o disparador Supabase→Actions permanece inativo.

Pesquisa em 25/10/2026, com documentação oficial. A recomendação é executar uma
única instância contínua em Docker, numa VPS ou num worker gerenciado. GitHub
Actions fica com testes, build e implantação. Supabase mantém o callback HTTPS,
tokens OAuth e persistência privada já existentes.

**Restrição do usuário: custo mensal zero.** A primeira opção a avaliar é uma
VM OCI Ampere A1 elegível ao Oracle Always Free, mantendo a conta no plano
gratuito. A documentação atual informa franquia de 1.500 OCPU-horas e 9.000
GB-horas por mês, equivalente a 2 OCPUs e 12 GB para tenancies Always Free.
Essa informação deve ser conferida no console antes de provisionar; referências
antigas a 4 OCPUs e 24 GB não correspondem à página consultada nesta pesquisa.

O caminho é condicional: pode faltar capacidade na região, a Oracle pode recuperar
VMs consideradas ociosas e a criação da conta exige cartão para verificação, com
possível autorização temporária. Isso não equivale a garantir disponibilidade
contínua gratuita. Não fazer upgrade para conta paga ou criar recursos apenas
cobertos pelos créditos temporários do trial. A imagem Linux e os navegadores
precisam ser validados em ARM antes da migração; nenhuma VM foi criada.

O Google oferece franquia recorrente de uma e2-micro em regiões específicas,
mas ela tem 1 GB de memória. O IPv4 público tem cobrança própria e a franquia de
tráfego de saída é limitada. Por isso, não é a primeira escolha para este bot com
dois navegadores e exigência de custo total zero. Railway Free oferece US$ 1 de
crédito mensal, o que não comprova capacidade de manter esta carga continuamente.
Render Free não oferece o worker persistente recomendado para este caso.

## Situação verificada

- Nenhum evento `schedule` registrado no workflow de produção.
- Supabase Cron `promos-gamer-dispatch` instalado, mas INATIVO.
- Último ciclo manual concluído às 22h42 de 25/10 (Brasília): 23 produtos,
  zero aprovados, 22 sem queda mínima e uma pendência de coleta.
- A ausência de promoção aprovada não é uma prova de monitor parado; os horários
  de `monitor_runs` e a origem do disparo são a evidência operacional.

## Comparação

| Opção | Adequação | Custo e limite |
| --- | --- | --- |
| Oracle Always Free A1 + Docker | Primeira opção sob a exigência de custo zero, se a conta e a região oferecerem capacidade e o teste ARM passar. | Franquia atual equivalente a 2 OCPUs/12 GB. Cartão para verificação, capacidade limitada e recuperação de instâncias ociosas. |
| VPS Linux + Docker | Boa para manter Chromium e sessão WhatsApp em disco persistente, com custo previsível. Exige manutenção do servidor. | Exemplo de referência: DigitalOcean Basic 2 GiB/1 vCPU por US$ 12/mês, sem adicionais. Dimensionamento precisa de medição; não é uma cotação final. |
| Worker Docker no Railway | Gerenciado, com volume persistente. Simplifica deploy e operação. | Hobby tem compromisso mínimo de US$ 5/mês, incluindo esse valor em consumo. Uso acima disso é cobrado; não é um pacote ilimitado. |
| Background worker no Render | Serviço contínuo e opção de disco persistente pago. | Cobrança de compute e disco conforme plano; escolher memória após medir os navegadores. |
| Cloud Run Jobs + Cloud Scheduler | Opção gerenciada para ciclos que terminam, com armazenamento externo. | Consumo variável; cada ciclo reinicia os processos. Mais adequado para coleta desacoplada de uma ponte WhatsApp persistente. |
| Supabase Cron | Bom como relógio para chamar um executor real. | Não hospeda, por si só, o navegador e a sessão WhatsApp. |
| GitHub Actions como executor de produção | Recomendação anterior revista. A gratuidade de runners públicos não resolve limites de finalidade e agendamento. | A documentação permite atrasos/descarte de cron, e os termos restringem uso como aplicação serverless e atividades fora do ciclo de desenvolvimento do software. |

O disparador Supabase→Actions preparado anteriormente continua inativo. Ele não
é a recomendação para hospedar este bot em produção. O token GitHub solicitado
para esse caminho não é necessário para a arquitetura recomendada; não é preciso
ativar `configurar-agendador.cmd` para migrar a uma VPS ou worker.

## Organização recomendada

1. Um worker contínuo, sem instâncias concorrentes do mesmo monitor.
2. Coleta das sete categorias a cada cinco minutos, com limite por loja e sem
   sobrepor ciclos quando uma coleta exceder o intervalo.
3. Fila `pending_offers` persistida, revalidação e reserva anterior ao envio.
4. Ponte WhatsApp no mesmo ambiente privado, mantendo a sessão em volume e o
   backup cifrado. Reconexão é tratada sem presumir que uma sessão nunca expire.
5. Callback e renovação do Mercado Livre continuam no Supabase.
6. Reinício automático do processo e diagnóstico de último ciclo. Um verificador
   externo deve detectar atraso, por exemplo, acima de 15 minutos; Docker reiniciar
   um processo encerrado não prova que um processo travado está saudável.
7. Backup do histórico, secrets fora do código e interrupção dos executores antigos
   antes da migração, evitando conflitos no estado e na sessão.

Nenhuma mudança de hospedagem ou contratação foi feita nesta pesquisa. A fila e
os filtros atuais podem ser aproveitados; a migração precisa adaptar o launcher,
persistência e verificação de saúde e validar uma coleta e uma entrega controlada.
Agendamento e hospedagem não liberam fontes de dados que ainda faltam: Amazon,
Magalu e Pichau seguem dependentes de acesso autorizado, e catálogo Mercado Livre
continua dependendo de disponibilidade verificável para publicar.

## Referências oficiais

- [GitHub: termos de Actions](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features#actions)
- [GitHub: eventos schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [Supabase: agendamento](https://supabase.com/docs/guides/functions/schedule-functions)
- [Supabase: limites de Edge Functions](https://supabase.com/docs/guides/functions/limits)
- [Docker: reinício automático](https://docs.docker.com/engine/containers/start-containers-automatically/)
- [DigitalOcean: preços de Droplets](https://www.digitalocean.com/pricing/droplets)
- [Railway: cobrança](https://docs.railway.com/pricing/understanding-your-bill)
- [Railway: volumes](https://docs.railway.com/volumes)
- [Railway: cron](https://docs.railway.com/cron-jobs)
- [Render: workers](https://render.com/docs/background-workers)
- [Render: discos](https://render.com/docs/disks)
- [Render: preços](https://render.com/pricing)
- [Cloud Run Jobs: agendamento](https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule)
- [Oracle: recursos Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- [Oracle: criação de conta gratuita](https://docs.oracle.com/pt-br/iaas/Content/GSG/Tasks/signingup_topic-Sign_Up_for_Free_Oracle_Cloud_Promotion.htm)
- [Google: franquia gratuita](https://docs.cloud.google.com/free/docs/free-cloud-features)
- [Google: memória e2-micro](https://docs.cloud.google.com/compute/docs/general-purpose-machines)
- [Google: cobrança de IP externo](https://cloud.google.com/vpc/network-pricing)
- [Railway: planos](https://docs.railway.com/pricing/plans)
- [Playwright: plataformas suportadas](https://playwright.dev/python/docs/intro)
