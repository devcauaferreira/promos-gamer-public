"""HTTP de leitura para APIs: falhas de acesso não geram martelamento."""
import json
import random
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from collectors.base import SourceError
from services.diagnostics import response_metadata, write_diagnostic


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Não encaminha Authorization para um destino recebido em redirecionamento.
        return None


def retry_seconds(value, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        try:
            return max(0, int((parsedate_to_datetime(value) - now).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            return None


class JsonHttpClient:
    def __init__(self, db, store, scope, opener=None, sleep=time.sleep):
        self.db, self.store, self.scope = db, store, scope
        self.opener = opener or build_opener(NoRedirect())
        self.sleep = sleep
        db.execute("""CREATE TABLE IF NOT EXISTS source_health (
            scope TEXT PRIMARY KEY, store TEXT NOT NULL, state TEXT NOT NULL,
            retry_at TEXT, updated_at TEXT NOT NULL)""")
        db.commit()

    def health(self):
        row = self.db.execute("SELECT state,retry_at FROM source_health WHERE scope=?", (self.scope,)).fetchone()
        if not row:
            return {"state": "ready_to_validate"}
        state, retry_at = row
        if state in ("auth_required", "access_denied"):
            return {"state": state, "error": "Acesso suspenso; revise credenciais/permissões e use --reset-source"}
        if retry_at and retry_at > datetime.now(timezone.utc).isoformat():
            return {"state": state, "retry_at": retry_at, "error": "Aguardando intervalo de nova tentativa"}
        if state == "operational":
            return {"state": "operational"}
        return {"state": "ready_to_validate"}

    def fail(self, state, delay=None):
        now = datetime.now(timezone.utc)
        try:
            retry_at = (now + timedelta(seconds=delay)).isoformat() if delay is not None else None
        except OverflowError:
            retry_at = datetime.max.replace(tzinfo=timezone.utc).isoformat()
        self.db.execute("INSERT OR REPLACE INTO source_health VALUES (?,?,?,?,?)",
                        (self.scope, self.store, state, retry_at, now.isoformat()))
        self.db.commit()

    def get(self, url, headers=None, operation="read"):
        health = self.health()
        if "error" in health:
            raise SourceError(health["state"], health["error"])
        for attempt in range(3):
            try:
                response = self.opener.open(Request(url, headers=headers or {}, method="GET"), timeout=20)
            except HTTPError as error:
                status, response_headers = error.code, error.headers
                try:
                    body = error.read(65536)
                finally:
                    error.close()
            except (URLError, TimeoutError, OSError):
                self.fail("network_error", 300)
                write_diagnostic(self.store, operation, {"state": "network_error"})
                raise SourceError("network_error", "Falha de conexão com a API; nova tentativa adiada") from None
            else:
                with response:
                    status, response_headers = response.status, response.headers
                    body = response.read(5_000_001)
                if len(body) > 5_000_000:
                    raise SourceError("invalid_response", "Resposta excede o limite de tamanho")
            metadata = response_metadata(url, status, response_headers, body)
            write_diagnostic(self.store, operation, metadata)
            if 200 <= status < 300:
                try:
                    data = json.loads(body)
                except (ValueError, UnicodeDecodeError):
                    raise SourceError("invalid_response", "API retornou conteúdo que não é JSON") from None
                self.fail("operational")
                return data
            if status in (401, 403):
                state = "auth_required" if status == 401 else "access_denied"
                self.fail(state)
                raise SourceError(state, f"API retornou HTTP {status}; revise acesso. Não haverá repetição automática")
            retry = retry_seconds(response_headers.get("Retry-After"))
            if status in (429, 503):
                if status == 503 and retry is None and attempt < 2:
                    self.sleep((0.5 * 2 ** attempt) + random.uniform(0, 0.2))
                    continue
                state = "rate_limited" if status == 429 else "temporarily_unavailable"
                self.fail(state, max(1, retry if retry is not None else 300))
                raise SourceError(state, f"HTTP {status}; nova tentativa adiada respeitando Retry-After")
            if status >= 500:
                self.fail("temporarily_unavailable", 300)
            if status == 404:
                raise SourceError("not_found", "Recurso não encontrado na API (HTTP 404)")
            raise SourceError("http_error", f"API retornou HTTP {status}; consulte reports/http.jsonl")
