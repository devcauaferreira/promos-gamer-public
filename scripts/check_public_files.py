"""Recusa arquivos privados e identificadores de instalação no código público."""
import re
import subprocess
from pathlib import Path, PurePosixPath


def private_path(name):
    path = PurePosixPath(name.lower())
    return (
        any(part in {"reports", "feeds", "backups", ".venv", "node_modules"}
            or part.startswith(".wwebjs") for part in path.parts)
        or (path.name.startswith(".env") and path.name != ".env.example")
        or path.name in {"settings.json", "products.json", ".bridge_token"}
        or bool(re.search(r"\.(?:sqlite3?|db|pem|key|p12|pfx|log|bundle)(?:$|[.-])", path.name))
        or path.name.startswith("remoteauth-")
    )


def main():
    files = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    problems = []
    patterns = {
        "ID real de grupo/conta WhatsApp": r"\b[0-9][0-9-]{9,}@(g\.us|c\.us|s\.whatsapp\.net)\b",
        "Referência real Supabase": r"\b[a-z]{20}\.supabase\.co\b",
        "Chave privada": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    }
    for name in filter(None, files):
        if private_path(name):
            problems.append((name, "arquivo privado"))
            continue
        content = Path(name).read_text(encoding="utf-8", errors="replace")
        for label, pattern in patterns.items():
            if re.search(pattern, content):
                problems.append((name, label))
    for name, label in problems:
        # Não imprimir o conteúdo encontrado.
        print(f"Bloqueado: {name}: {label}")
    if problems:
        return 1
    print("Nenhum arquivo privado ou identificador de instalação detectado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
