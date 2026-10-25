"""Executa tarefas com credenciais sem expor sua saída nos logs públicos do Actions."""
import argparse
import subprocess
import sys
from pathlib import Path


def run_job(mode, limit=20, send_test=False):
    if mode not in ("collect", "publish", "connect"):
        raise ValueError("Tarefa não suportada")
    if not 1 <= limit <= 500 or (send_test and mode != "connect"):
        raise ValueError("Opções inválidas")
    if mode == "collect":
        command = [sys.executable, "cloud_run.py", "--check-candidates", "--limit", str(limit)]
    elif mode == "publish":
        command = [sys.executable, "whatsapp_cloud_job.py", "--limit", str(limit)]
    else:
        command = [sys.executable, "whatsapp_cloud_job.py", "--connect"]
        if send_test:
            command.append("--test")
    # Não enviar este arquivo a artifacts/caches: pode conter dados privados.
    # O runner é efêmero; banco e sessão continuam persistidos no Supabase.
    folder = Path("reports")
    folder.mkdir(exist_ok=True)
    print(f"Tarefa {mode} iniciada; saída detalhada restrita ao runner.", flush=True)
    with (folder / "cloud-job-private.log").open("ab") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print(f"Tarefa {mode} falhou. Execute o diagnóstico em ambiente privado.", flush=True)
        return 1
    print(f"Tarefa {mode} concluída.", flush=True)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("collect", "publish", "connect"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    try:
        code = run_job(args.mode, args.limit, args.test)
    except Exception:
        # Mensagens de exceção podem conter URLs, credenciais e IDs privados.
        print("Não foi possível executar a tarefa. Consulte a configuração em ambiente privado.", flush=True)
        code = 1
    raise SystemExit(code)
