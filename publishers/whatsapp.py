import json
import os
import base64
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


def product_image(image_url):
    """Obtém apenas fotos oficiais da KaBuM, com limite de tamanho e sem redirecionar."""
    parsed = urlparse(image_url)
    if (parsed.scheme != "https" or parsed.hostname != "images.kabum.com.br"
            or not parsed.path.startswith("/produtos/fotos/") or parsed.query or parsed.fragment
            or parsed.username or parsed.password):
        return None
    from services.http_client import NoRedirect
    from urllib.request import build_opener
    request = Request(image_url, headers={"Accept": "image/jpeg,image/png,image/webp"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            mime = response.headers.get_content_type()
            if mime not in ("image/jpeg", "image/png", "image/webp"):
                return None
            data = response.read(3_000_001)
            if not data or len(data) > 3_000_000:
                return None
            return {"mimetype": mime, "data": base64.b64encode(data).decode("ascii")}
    except (OSError, ValueError):
        return None


class WhatsAppDeliveryError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def publish(message, group_id, image_url="", require_image=False):
    token = bridge_token()
    if len(token) < 24:
        raise ValueError("Defina WHATSAPP_BRIDGE_TOKEN com pelo menos 24 caracteres")
    if not group_id.endswith("@g.us"):
        raise ValueError("Configure o ID exato do grupo do WhatsApp")
    base_url = "http://127.0.0.1:8787" if runner_bridge() else (validate_remote_bridge() if secret("WHATSAPP_BRIDGE_URL") else "http://127.0.0.1:8787")
    if os.environ.get("GITHUB_ACTIONS") == "true" and not runner_bridge() and not secret("WHATSAPP_BRIDGE_URL"):
        raise ValueError("Configure uma ponte externa HTTPS antes de publicar pelo GitHub Actions")
    payload = {"group_id": group_id, "message": message}
    if image_url:
        photo = product_image(image_url)
        if photo:
            payload["image"] = photo
    if require_image and 'image' not in payload:
        raise ValueError('Foto indisponível antes do envio; nenhuma mensagem enviada.')
    request = Request(base_url + "/send",
                      data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
                      method="POST")
    from services.http_client import NoRedirect
    from urllib.request import build_opener
    from urllib.error import HTTPError, URLError
    try:
        with build_opener(NoRedirect()).open(request, timeout=120) as response:
            result = json.load(response)
    except HTTPError as error:
        code = 'whatsapp_bridge_http_error'
        try:
            response = json.loads(error.read(8192))
            if isinstance(response, dict) and response.get('error_code') in ('send_failed', 'confirmation_missing'):
                code = 'whatsapp_' + response['error_code']
        except (ValueError, TypeError, OSError):
            pass
        finally:
            error.close()
        raise WhatsAppDeliveryError(code) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise WhatsAppDeliveryError('whatsapp_transport_unknown') from None
    if not isinstance(result, dict) or not result.get("message_id"):
        raise WhatsAppDeliveryError('whatsapp_confirmation_missing')
    return result["message_id"]
