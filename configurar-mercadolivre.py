"""Recebe as credenciais em terminal local e configura o OAuth já publicado."""
import getpass
import json
import subprocess
import webbrowser
from pathlib import Path

from services.cloud import cloud_request, project_url


if __name__ == "__main__":
    redirect = project_url() + "/functions/v1/mercadolivre-callback"
    print("Cadastre exatamente esta URI de redirect na sua aplicacao Mercado Livre:")
    print(redirect)
    print("Ative PKCE S256 e somente as permissoes necessarias ao projeto.")
    print("As credenciais abaixo ficam no computador e no Supabase, nunca no Git ou chat.")
    path = Path("supabase/functions/.env")
    values = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line and not line.startswith("#"))
    current_id = values.get("ML_CLIENT_ID", "")
    client_id = input(f"APP ID [{current_id}] (Enter mantem): " if current_id else "APP ID: ").strip() or current_id
    if not client_id.isdigit():
        raise SystemExit("APP ID invalido; nenhuma alteracao realizada.")
    client_secret = getpass.getpass("Client Secret (nao sera exibido): ").strip()
    if not client_secret or any(character in client_secret for character in "\r\n"):
        raise SystemExit("Client Secret invalido; nenhuma alteracao realizada.")
    values.update(ML_CLIENT_ID=client_id, ML_CLIENT_SECRET=client_secret, ML_REDIRECT_URI=redirect)
    path.write_text("\n".join(name + "=" + value for name, value in values.items()) + "\n", encoding="utf-8")
    ref = project_url().split("//", 1)[1].split(".", 1)[0]
    result = subprocess.run(["npx.cmd", "--yes", "supabase@2.122.0", "--agent", "no", "--output-format", "text",
                             "secrets", "set", "--project-ref", ref, "--env-file", str(path)],
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise SystemExit("Falha ao cadastrar secrets. Confirme o login do Supabase; credenciais nao foram exibidas.")
    settings_path = Path("settings.json")
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings.setdefault("sources", {}).setdefault("mercadolivre", {})["oauth_mode"] = "supabase"
        settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    authorization = cloud_request("mercadolivre-callback/start")
    webbrowser.open(authorization["authorization_url"])
    print("Credenciais cadastradas. Conclua a autorizacao na pagina oficial aberta no navegador.")
