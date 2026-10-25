"""Diagnostica a própria resposta do Playwright, sem requisição paralela."""
from collectors.base import SourceError
from services.diagnostics import response_metadata, write_diagnostic
from services.http_client import retry_seconds


def navigate(page, url, client, operation, timeout):
    state = client.health() if client else {}
    if "error" in state:
        raise SourceError(state["state"], state["error"])
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    except Exception:
        if client:
            client.fail("network_error", 300)
        raise SourceError("network_error", "Navegação falhou; nova tentativa adiada") from None
    if not response:
        raise SourceError("invalid_response", "Navegador não recebeu resposta HTTP")
    headers = response.headers
    try:
        body = response.body()[:65536] if response.status >= 400 else b""
    except Exception:
        body = b""
    if client:
        write_diagnostic(client.store, operation, response_metadata(response.url, response.status, headers, body))
    if response.status in (401, 403, 429, 503):
        state = {401: "auth_required", 403: "access_denied", 429: "rate_limited", 503: "temporarily_unavailable"}[response.status]
        if client:
            delay = None if response.status in (401, 403) else max(1, retry_seconds(headers.get("retry-after")) or 300)
            client.fail(state, delay)
        raise SourceError(state, f"HTTP {response.status}; consulta suspensa conforme política da fonte")
    if response.status >= 400:
        raise SourceError("http_error", f"HTTP {response.status}")
    return response
