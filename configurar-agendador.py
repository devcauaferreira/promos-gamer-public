"""Cadastra um token restrito no Vault e ativa o disparador Supabase de cinco minutos."""
import getpass
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from services.http_client import NoRedirect

ROOT = Path(__file__).resolve().parent


def sql_literal(value):
    return "'" + value.replace("'", "''") + "'"


def run_sql(query):
    folder = ROOT / 'reports'
    folder.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', dir=folder, encoding='utf-8', delete=False) as file:
        file.write(query)
        path = Path(file.name)
    try:
        result = subprocess.run(['npx.cmd', '--yes', 'supabase@2.122.0', '--agent', 'no',
                                 '--output-format', 'json', 'db', 'query', '--linked', '--file', str(path)],
                                cwd=ROOT, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise RuntimeError('Falha no Supabase. Confira o login e o projeto vinculado; nenhum segredo foi exibido.')
        return json.loads(result.stdout[result.stdout.find('['):])
    finally:
        path.unlink(missing_ok=True)


def main():
    origin = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], cwd=ROOT, text=True).strip()
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?', origin)
    if not match:
        raise ValueError('Configure origin como o endereço HTTPS do repositório de produção.')
    repository = match.group(1)
    print('Crie um fine-grained token apenas para este repositório, com Actions: Read and write.')
    print('Não selecione outros repositórios ou permissões de conteúdo.')
    token = getpass.getpass('Token (entrada oculta; não será salvo no Git): ').strip()
    if not re.fullmatch(r'github_pat_[A-Za-z0-9_]{20,}', token):
        raise ValueError('Use um fine-grained token válido do GitHub.')
    base = 'https://api.github.com/repos/' + repository + '/actions/workflows/promos.yml'
    request = Request(base, headers={'Authorization': 'Bearer ' + token,
                      'Accept': 'application/vnd.github+json', 'User-Agent': 'promos-gamer-setup'})
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        workflow = json.load(response)
    if workflow.get('state') != 'active':
        raise ValueError('O workflow de produção precisa estar ativo.')
    # Instalado inativo; uma falha na configuração não inicia consultas recorrentes.
    run_sql((ROOT / 'supabase/scheduler.sql').read_text(encoding='utf-8'))
    for name, value in [('promos_github_dispatch_url', base + '/dispatches'), ('promos_github_actions_token', token)]:
        run_sql(f'''do $$ declare existing uuid; begin
          select id into existing from vault.secrets where name={sql_literal(name)};
          if existing is null then
            perform vault.create_secret({sql_literal(value)}, {sql_literal(name)});
          else
            perform vault.update_secret(existing, {sql_literal(value)});
          end if;
        end $$; select true as saved;''')
    result = run_sql('select private.promos_scheduler_tick() as request_id;')
    request_id = result[0]['request_id']
    confirmed = False
    for _ in range(6):
        time.sleep(2)
        rows = run_sql(f'select status_code from net._http_response where id={int(request_id)};')
        if rows:
            if rows[0]['status_code'] != 204:
                raise ValueError('GitHub não aceitou o disparo. Confira Actions: Read and write e a validade do token. Cron permanece inativo.')
            confirmed = True
            break
    if not confirmed:
        raise RuntimeError('Disparo sem confirmação no prazo. Cron permanece inativo; verifique o job antes de repetir.')
    run_sql("select cron.alter_job(jobid, active := true) from cron.job where jobname='promos-gamer-dispatch';")
    print('GitHub confirmou o disparo. Supabase Cron ativado a cada cinco minutos.')
    print('O runner continua no GitHub Actions. Verifique a próxima execução antes de encerrar a validação.')


if __name__ == '__main__':
    try:
        main()
    except (HTTPError, URLError):
        raise SystemExit('GitHub recusou a consulta ou houve falha de rede. Nenhuma credencial foi exibida.')
    except Exception as error:
        # Erros de bibliotecas podem incluir URL ou saída da CLI; não imprimi-los.
        if isinstance(error, (ValueError, RuntimeError)):
            raise SystemExit(str(error))
        raise SystemExit('Configuração não concluída. Nenhuma credencial foi exibida; confira o ambiente local.')
