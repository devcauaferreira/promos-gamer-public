"""Consulta a última execução persistida sem enviar mensagens nem alterar produção."""
import base64
import json
import sqlite3
from contextlib import closing

from services.cloud import cloud_request


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
                if row[5]:
                    info = json.loads(row[5])
                    print('Avaliados:', info['evaluated'], '| aprovados:', info['approved'],
                          '| enviados:', info['sent'], '| erros:', info['errors'])
                    if info.get('persistence_errors'):
                        print('Envios confirmados com pendência de persistência:', info['persistence_errors'])
                    for reason, count in info['reasons'].items():
                        print(reason + ':', count)
                    for code, count in info.get('source_failures', {}).items():
                        print('Pendência ' + code + ':', count)
        else:
            print('Registro de ciclos ainda não implantado; consulta ao histórico abaixo.')
        if 'prices' in tables:
            print('Último preço coletado (UTC):', db.execute('SELECT MAX(observed_at) FROM prices').fetchone()[0])
        if 'publications' in tables:
            print('Promoções com envio confirmado:', db.execute('SELECT COUNT(*) FROM publications').fetchone()[0])
        if 'pending_offers' in tables:
            print('Candidatos aguardando envio:', db.execute("SELECT COUNT(*) FROM pending_offers WHERE state='pending'").fetchone()[0])


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Não foi possível consultar o estado privado. Verifique a conexão e a configuração local.')
