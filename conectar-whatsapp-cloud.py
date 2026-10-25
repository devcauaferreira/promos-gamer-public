"""Exibe no navegador local o QR privado gerado no GitHub Actions."""
import os
import subprocess
import webbrowser
from services.secrets import secret

if __name__ == "__main__":
    env = dict(os.environ)
    for name in ("SUPABASE_PROJECT_URL", "BOT_API_SECRET", "WHATSAPP_SESSION_KEY"):
        env[name] = secret(name)
        if not env[name]:
            raise SystemExit(f"Configure {name} em .env antes de conectar a nuvem")
    process = subprocess.Popen(["node", "conectar-whatsapp-cloud.cjs"],env=env,stdout=subprocess.PIPE,text=True)
    try:
        url = process.stdout.readline().strip()
        if not url.startswith("http://127.0.0.1:"):
            raise RuntimeError("Não foi possível abrir o visualizador privado")
        webbrowser.open(url)
        print("QR privado aberto no navegador. Aguarde o workflow concluir e feche esta janela.",flush=True)
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
