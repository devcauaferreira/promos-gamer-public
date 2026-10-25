-- Dados privados. Nenhuma policy concede acesso a anon/authenticated.
create table public.ml_oauth_pending (
  state_hash text primary key,
  encrypted_verifier text not null,
  expires_at timestamptz not null
);
create table public.ml_oauth_credentials (
  id text primary key check (id = 'mercadolivre'),
  encrypted_tokens text not null,
  expires_at timestamptz not null,
  generation uuid not null,
  refresh_lock text,
  updated_at timestamptz not null default now()
);
create table public.promos_runtime_state (
  id text primary key check (id = 'main'),
  version bigint not null default 0,
  payload text,
  updated_at timestamptz not null default now()
);
insert into public.promos_runtime_state(id) values ('main');
alter table public.ml_oauth_pending enable row level security;
alter table public.ml_oauth_credentials enable row level security;
alter table public.promos_runtime_state enable row level security;
revoke all on public.ml_oauth_pending, public.ml_oauth_credentials, public.promos_runtime_state from anon, authenticated;
grant all on public.ml_oauth_pending, public.ml_oauth_credentials, public.promos_runtime_state to service_role;
