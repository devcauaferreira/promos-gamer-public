"""Consulta a última execução persistida sem enviar mensagens nem alterar produção."""
import base64
import json
import sqlite3
from contextlib import closing

from services.cloud import cloud_request


def print_summary(info):
    print('Avaliados:', info.get('evaluated', 0), '| aprovados:', info.get('approved', 0),
          '| enviados:', info.get('sent', 0), '| erros:', info.get('errors', 0))
    if info.get('persistence_errors'):
        print('Envios confirmados com pendência de persistência:', info['persistence_errors'])
    for reason, count in info.get('reasons', {}).items():
        print(reason + ':', count)
    for code, count in info.get('source_failures', {}).items():
        print('Pendência ' + code + ':', count)
    for store, count in info.get('observations', {}).items():
        print('Observações registradas ' + store + ':', count)
    operation = info.get('operation', {})
    policy = operation.get('policy', {})
    if policy:
        print('Regra efetiva:', policy.get('minimum_discount_percent'), '% | janela:',
              policy.get('history_days'), 'dias | mínimo anterior:', policy.get('minimum_history_days'),
              'dia(s) | lote:', policy.get('products_per_run'))
    coverage = operation.get('coverage', {})
    if coverage:
        print('Produtos ativos no rodízio:', coverage.get('active_total', 0),
              '| volta completa estimada:', coverage.get('estimated_sweep_minutes'),
              'min (exclui preparação e atrasos)')
        for store, row in coverage.get('stores', {}).items():
            print('Cobertura ' + store + ': ativos=' + str(row.get('active', 0))
                  + ', nunca checados=' + str(row.get('unchecked', 0))
                  + ', checagem mais antiga (UTC)=' + str(row.get('oldest_checked_at')))
    for store, row in operation.get('sources', {}).items():
        print('Fonte ' + store + ': ' + row.get('state', 'unknown') + ' (' + row.get('mode', 'unknown') + ')')
    queues = operation.get('queues', {})
    if queues:
        print('Fila: pendentes=', queues.get('pending', 0), '| candidatos incertos=', queues.get('uncertain', 0),
              '| tentativas incertas=', queues.get('uncertain_dispatches', 0))
    for store, row in info.get('funnel', {}).items():
        print('Etapas ' + store + ': coletados=' + str(row.get('collected', 0))
              + ', disponíveis=' + str(row.get('available', 0))
              + ', com histórico=' + str(row.get('history_ready', 0))
              + ', atingiram desconto=' + str(row.get('discount_met', 0))
              + ', aprovados=' + str(row.get('approved', 0)) + ', enviados=' + str(row.get('sent', 0)))


def main():
    result = cloud_request('promos-state', 'GET')
    if not result.get('payload'):
        print('Estado da nuvem ainda não inicializado.')
        return
    with closing(sqlite3.connect(':memory:')) as db:
        db.deserialize(base64.b64decode(result['payload'], validate=True))
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'monitor_runs' in tables:
            row = db.execute('SELECT mode,event,started_at,finished_at,status,summary_json FROM monitor_runs '
                             'ORDER BY started_at DESC LIMIT 1').fetchone()
            if row:
                print('Último ciclo (UTC):', row[2], '| término:', row[3], '| estado:', row[4])
                print('Modo:', row[0], '| origem:', row[1])
                if row[4] == 'running':
                    completed = db.execute('SELECT mode,event,started_at,finished_at,status,summary_json '
                                           "FROM monitor_runs WHERE status<>'running' "
                                           'ORDER BY started_at DESC LIMIT 1').fetchone()
                    if completed:
                        row = completed
                        print('Último ciclo concluído (UTC):', row[2], '| término:', row[3], '| estado:', row[4])
                if row[5]:
                    print_summary(json.loads(row[5]))
        else:
            print('Registro de ciclos ainda não implantado; consulta ao histórico abaixo.')
        if 'prices' in tables:
            print('Último preço coletado (UTC):', db.execute('SELECT MAX(observed_at) FROM prices').fetchone()[0])
        if 'publications' in tables:
            print('Promoções com envio confirmado:', db.execute('SELECT COUNT(*) FROM publications').fetchone()[0])
        if 'pending_offers' in tables:
            print('Candidatos aguardando envio:', db.execute("SELECT COUNT(*) FROM pending_offers WHERE state='pending'").fetchone()[0])
            print('Candidatos com resultado incerto:', db.execute("SELECT COUNT(*) FROM pending_offers WHERE state='uncertain'").fetchone()[0])
        if 'dispatches' in tables:
            print('Tentativas com resultado incerto:', db.execute("SELECT COUNT(*) FROM dispatches WHERE state='uncertain'").fetchone()[0])
        if 'whatsapp_health' in tables:
            health = db.execute('SELECT checked_at,ready,group_found,session_saved FROM whatsapp_health '
                                'ORDER BY checked_at DESC LIMIT 1').fetchone()
            if health:
                print('Última verificação WhatsApp (UTC):', health[0], '| conexão:', bool(health[1]),
                      '| grupo encontrado:', bool(health[2]), '| sessão salva:', bool(health[3]))
        if 'price_observations' in tables:
            print('Observações persistidas por loja:', db.execute(
                'SELECT store,COUNT(*),MAX(observed_at) FROM price_observations GROUP BY store').fetchall())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Não foi possível consultar o estado privado. Verifique a conexão e a configuração local.')
