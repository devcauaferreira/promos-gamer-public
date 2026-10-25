create table public.ml_oauth_diagnostics (
  id uuid primary key,
  created_at timestamptz not null default now(),
  phase text not null,
  code text not null,
  provider_status integer,
  provider_code text
);
alter table public.ml_oauth_diagnostics enable row level security;
revoke all on public.ml_oauth_diagnostics from anon, authenticated;
grant all on public.ml_oauth_diagnostics to service_role;
