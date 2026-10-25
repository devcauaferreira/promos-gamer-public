"""Diagnósticos estruturados sem cabeçalhos de autenticação ou corpo bruto."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def safe_url(url):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))


def response_metadata(url, status, headers, body=b""):
    headers = {key.lower(): value for key, value in headers.items()}
    # Corpo bruto pode incluir dados pessoais: guarda tipo, tamanho e hash, não conteúdo.
    content_type = headers.get("content-type", "").split(";")[0]
    content_type = content_type if re.fullmatch(r"[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+", content_type) else "unknown"
    result = {"url": safe_url(url), "http_status": status,
              "content_type": content_type,
              "body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest()}
    retry = headers.get("retry-after")
    if retry and re.fullmatch(r"[0-9]+|[A-Za-z]{3}, [0-9]{2} [A-Za-z]{3} [0-9]{4} [0-9:]{8} GMT", str(retry)):
        result["retry_after"] = str(retry)[:100]
    try:
        payload = json.loads(body)
        if isinstance(payload, dict):
            code = payload.get("error") or payload.get("code")
            if isinstance(code, str) and code in {"forbidden", "unauthorized", "invalid_token", "invalid_scope", "access_denied", "not_found", "bad_request", "too_many_requests", "throttled", "TokenExpired", "AssociateNotEligible"}:
                result["error_code"] = code
    except (ValueError, UnicodeDecodeError):
        pass
    return result


def write_diagnostic(store, operation, metadata, path=Path("reports/http.jsonl")):
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), "store": store,
           "operation": operation, **metadata}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")
