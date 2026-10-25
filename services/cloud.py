"""Cliente restrito às funções HTTPS do projeto Supabase configurado."""
import base64
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener

from services.http_client import NoRedirect
from services.secrets import secret


def project_url():
    url = secret("SUPABASE_PROJECT_URL").rstrip("/")
    parsed = urlparse(url)
    if (parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".supabase.co")
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("Configure SUPABASE_PROJECT_URL como https://SEU-PROJETO.supabase.co")
    return url


def cloud_request(function, method="POST", payload=None):
    token = secret("BOT_API_SECRET")
    if len(token) < 32:
        raise ValueError("Configure BOT_API_SECRET com pelo menos 32 caracteres")
    url = project_url() + "/functions/v1/" + function
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=data, method=method, headers={"Authorization": "Bearer " + token,
                      "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=40) as response:
            raw = response.read(7_000_100)
        if len(raw) > 7_000_000:
            raise RuntimeError("Resposta da função excede o limite")
        return json.loads(raw)
    except HTTPError as exc:
        code = exc.code
        exc.close()
        raise RuntimeError(f"Função Supabase retornou HTTP {code}; revise configuração/autorização. Nenhum segredo foi registrado") from None
    except (URLError, TimeoutError, ValueError):
        raise RuntimeError("Falha ao consultar a função Supabase; nenhum segredo foi registrado") from None


def ml_cloud_token():
    result = cloud_request("mercadolivre-callback/token")
    token = result.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Callback não forneceu token; conclua a autorização do Mercado Livre")
    return token


class CloudState:
    def __init__(self, path):
        self.path, self.version = Path(path), None

    def restore(self):
        result = cloud_request("promos-state", "GET")
        self.version = result["version"]
        if type(self.version) is not int or self.version < 0:
            raise RuntimeError("Versão do estado remoto inválida")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if result.get("payload") is not None:
            data = base64.b64decode(result["payload"], validate=True)
            if len(data) > 5_000_000 or not data.startswith(b"SQLite format 3\x00"):
                raise RuntimeError("Snapshot remoto inválido; execução interrompida")
            self.path.write_bytes(data)
            with closing(sqlite3.connect(self.path)) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Banco remoto não passou na verificação de integridade")
        elif self.path.exists():
            raise RuntimeError("Estado remoto vazio e banco local existente; migração explícita necessária")

    def checkpoint(self, db):
        if self.version is None:
            raise RuntimeError("Restaure o estado antes de gravar")
        db.commit()
        data = db.serialize()
        if len(data) > 5_000_000:
            raise RuntimeError("Banco excede o limite de snapshot; migre a persistência antes de continuar")
        result = cloud_request("promos-state", "PUT", {"version": self.version, "payload": base64.b64encode(data).decode()})
        if result.get("version") != self.version + 1:
            raise RuntimeError("Versão remota inesperada; não repetir a gravação automaticamente")
        self.version = result["version"]

    def initialize_from_local(self):
        result = cloud_request("promos-state", "GET")
        if result.get("payload") is not None or result.get("version") != 0:
            raise RuntimeError("Estado remoto já inicializado; o banco não será sobrescrito")
        if not self.path.is_file():
            raise RuntimeError("Banco local não encontrado")
        self.version = 0
        with closing(sqlite3.connect(self.path)) as db:
            self.checkpoint(db)
