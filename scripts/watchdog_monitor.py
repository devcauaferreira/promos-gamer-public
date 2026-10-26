"""Recupera o encadeamento parado sem disputar a fila de coleta/publicação."""
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from scripts.continue_monitor import NoRedirect


def recover_monitor(env=None, opener=None):
    env = os.environ if env is None else env
    if env.get('PROMOS_CLOUD_ENABLED') != 'true' or env.get('PROMOS_CHAIN_ENABLED') != 'true':
        print('Monitor ou encadeamento desativado; nenhuma recuperação.', flush=True)
        return False
    repository, token, own_run = (env.get(key, '') for key in
                                  ('GITHUB_REPOSITORY', 'GH_TOKEN', 'GITHUB_RUN_ID'))
    if (env.get('GITHUB_ACTIONS') != 'true' or not token or not own_run.isdigit()
            or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository)
            or env.get('GITHUB_API_URL', 'https://api.github.com') != 'https://api.github.com'):
        raise ValueError('Recuperação exige o ambiente oficial do GitHub Actions.')
    opener = opener or build_opener(NoRedirect())
    raw_limit = env.get('PROMOS_PRODUCT_LIMIT') or '20'
    if not re.fullmatch(r'[0-9]{1,3}', raw_limit) or not 1 <= int(raw_limit) <= 500:
        raise ValueError('Limite de produtos inválido.')
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'Content-Type': 'application/json', 'User-Agent': 'promos-gamer-watchdog'}
    base = 'https://api.github.com/repos/' + repository + '/actions'

    def request(path, method='GET', payload=None):
        req = Request(base + path, method=method, headers=headers,
                      data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with opener.open(req, timeout=20) as response:
                if method == 'POST':
                    if response.status != 204:
                        raise RuntimeError('GitHub não confirmou a recuperação.')
                    return None
                return json.loads(response.read(2_000_000))
        except HTTPError as error:
            code = error.code
            error.close()
            raise RuntimeError(f'Consulta de recuperação recusada: HTTP {code}.') from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise RuntimeError('Não foi possível verificar a continuidade; nenhum disparo às cegas.') from None

    # Consulta os workflows relevantes para respeitar também uma conexão WhatsApp em
    # andamento. Falha de leitura nunca é interpretada como monitor parado.
    active = {'queued', 'pending', 'in_progress', 'waiting', 'requested'}
    for status in sorted(active):
        for workflow in ('promos.yml', 'whatsapp-connect.yml'):
            data = request('/workflows/' + workflow + '/runs?status=' + status + '&branch=main&per_page=100')
            if not isinstance(data, dict) or not isinstance(data.get('workflow_runs'), list):
                raise RuntimeError('Resposta inválida ao verificar rodadas ativas.')
            for run in data['workflow_runs']:
                if str(run.get('id')) != own_run and run.get('status') in active:
                    print('Rodada ativa encontrada; nenhum disparo adicional.', flush=True)
                    return False
    request('/workflows/promos.yml/dispatches', 'POST',
            {'ref': 'main', 'inputs': {'publish': 'true', 'limit': str(int(raw_limit)),
                                      'source': 'self_chain', 'not_before': ''}})
    print('Monitor sem rodada ativa; recuperação registrada.', flush=True)
    return True


if __name__ == '__main__':
    try:
        recover_monitor()
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
