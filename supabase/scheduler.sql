-- Disparador externo. Credenciais são cadastradas pelo auxiliar local no Vault.
-- Instalar este arquivo deixa o job INATIVO até a configuração ser concluída.
create extension if not exists pg_cron;
create extension if not exists pg_net with schema extensions;
create schema if not exists private;

create or replace function private.promos_scheduler_tick()
returns bigint language plpgsql security definer set search_path = '' as $$
declare
  endpoint text;
  credential text;
begin
  select decrypted_secret into endpoint from vault.decrypted_secrets
    where name = 'promos_github_dispatch_url';
  select decrypted_secret into credential from vault.decrypted_secrets
    where name = 'promos_github_actions_token';
  if endpoint is null or credential is null then return null; end if;
  if endpoint !~ '^https://api[.]github[.]com/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/workflows/promos[.]yml/dispatches$'
     or credential not like 'github_pat_%' then
    raise exception 'Invalid scheduler configuration';
  end if;
  return net.http_post(
    url := endpoint,
    headers := jsonb_build_object('Authorization', 'Bearer ' || credential,
      'Accept', 'application/vnd.github+json', 'Content-Type', 'application/json',
      'User-Agent', 'promos-gamer-scheduler'),
    body := '{"ref":"main","inputs":{"publish":"true","limit":"20","source":"supabase_cron"}}'::jsonb,
    timeout_milliseconds := 10000
  );
end;
$$;
revoke all on function private.promos_scheduler_tick() from public, anon, authenticated;
select cron.schedule('promos-gamer-dispatch', '*/5 * * * *', 'select private.promos_scheduler_tick();');
select cron.alter_job(jobid, active := false) from cron.job where jobname = 'promos-gamer-dispatch';
