"""Encadeia uma rodada futura com o token temporário e limitado do próprio job."""
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def continue_monitor(env=None, opener=None, clock=time.time, sleep=time.sleep):
    env = os.environ if env is None else env
    if env.get('PROMOS_CHAIN_ENABLED') != 'true':
        print('Encadeamento desativado; nenhuma próxima rodada criada.', flush=True)
        return False
    repository = env.get('GITHUB_REPOSITORY', '')
    token = env.get('GH_TOKEN', '')
    if (env.get('GITHUB_ACTIONS') != 'true' or not token
            or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository)
            or env.get('GITHUB_API_URL', 'https://api.github.com') != 'https://api.github.com'):
        raise ValueError('Encadeamento exige o ambiente oficial do GitHub Actions.')
    now = clock()
    raw_slot = env.get('NEXT_SLOT', '')
    if raw_slot and not re.fullmatch(r'[0-9]{10}', raw_slot):
        raise ValueError('Horário de rodada inválido.')
    slot = float(raw_slot) if raw_slot else now
    if slot > now + 600:
        raise ValueError('Horário futuro excede o limite permitido.')
    next_slot = int(max(now, slot) + 300)
    payload = {'ref': 'main', 'inputs': {'publish': 'true', 'limit': '20',
               'source': 'self_chain', 'not_before': str(next_slot)}}
    request = Request('https://api.github.com/repos/' + repository + '/actions/workflows/promos.yml/dispatches',
                      data=json.dumps(payload).encode(), method='POST',
                      headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                               'Content-Type': 'application/json', 'User-Agent': 'promos-gamer-continuation'})
    opener = opener or build_opener(NoRedirect())
    # Apenas uma rodada fica pendente no grupo de concorrência. Se a resposta do
    # POST se perder, uma repetição substitui a rodada pendente, sem paralelismo.
    for attempt in range(3):
        try:
            with opener.open(request, timeout=20) as response:
                if response.status != 204:
                    raise RuntimeError('GitHub não confirmou o próximo disparo.')
            break
        except HTTPError as error:
            code = error.code
            error.close()
            if code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f'Próximo disparo recusado: HTTP {code}.') from None
            sleep(2 ** attempt)
        except (URLError, TimeoutError, OSError):
            if attempt == 2:
                raise RuntimeError('Não foi possível confirmar o próximo disparo.') from None
            sleep(2 ** attempt)
    print('Próxima rodada registrada para ' + datetime.fromtimestamp(next_slot, timezone.utc).isoformat(), flush=True)
    # O sucessor já está na fila antes da coleta: falhas posteriores desta rodada
    # não eliminam sua continuação. Aguarda o horário recebido sem sobrepor jobs.
    remaining = slot - clock()
    while remaining > 0:
        sleep(min(remaining, 30))
        remaining = slot - clock()
    return True


if __name__ == '__main__':
    try:
        continue_monitor()
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
