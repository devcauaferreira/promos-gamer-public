import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from services.secrets import secret


def bridge_token():
    file = Path(__file__).resolve().parent.parent / ".bridge_token"
    return secret("WHATSAPP_BRIDGE_TOKEN") or (file.read_text().strip() if file.exists() else "")


def validate_remote_bridge():
    url = secret("WHATSAPP_BRIDGE_URL").rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("No GitHub Actions, configure WHATSAPP_BRIDGE_URL como uma ponte HTTPS externa persistente")
    if parsed.hostname in ("localhost", "127.0.0.1", "::1") or len(bridge_token()) < 24:
        raise ValueError("A ponte local do computador não pode ser usada no runner hospedado")
    return url


def runner_bridge():
    return os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("WHATSAPP_RUNNER_BRIDGE") == "true"


def validate_publish_bridge():
    if not runner_bridge():
        return validate_remote_bridge()
    request = Request("http://127.0.0.1:8787/health", headers={"Authorization": "Bearer " + bridge_token()})
    with urlopen(request, timeout=15) as response:
        status = json.load(response)
    if not status.get("ready") or not status.get("group_found") or not status.get("session_saved"):
        raise ValueError("WhatsApp do runner ainda não está pronto para publicar")
    return "http://127.0.0.1:8787"


def publish(message, group_id):
    token = bridge_token()
    if len(token) < 24:
        raise ValueError("Defina WHATSAPP_BRIDGE_TOKEN com pelo menos 24 caracteres")
    if not group_id.endswith("@g.us"):
        raise ValueError("Configure o ID exato do grupo do WhatsApp")
    base_url = "http://127.0.0.1:8787" if runner_bridge() else (validate_remote_bridge() if secret("WHATSAPP_BRIDGE_URL") else "http://127.0.0.1:8787")
    if os.environ.get("GITHUB_ACTIONS") == "true" and not runner_bridge() and not secret("WHATSAPP_BRIDGE_URL"):
        raise ValueError("Configure uma ponte externa HTTPS antes de publicar pelo GitHub Actions")
    request = Request(base_url + "/send",
                      data=json.dumps({"group_id": group_id, "message": message}).encode(),
                      headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
                      method="POST")
    from services.http_client import NoRedirect
    from urllib.request import build_opener
    with build_opener(NoRedirect()).open(request, timeout=90) as response:
        result = json.load(response)
    if not result.get("message_id"):
        raise RuntimeError("WhatsApp não confirmou o identificador da mensagem")
    return result["message_id"]
