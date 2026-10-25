"""Lê credenciais locais; nunca as inclui em configurações ou relatórios."""
import os
from pathlib import Path


def secret(name):
    if name in os.environ:
        return os.environ[name].strip()
    file = Path(__file__).resolve().parent.parent / ".env"
    if file.exists():
        for line in file.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and key == name:
                return value.strip().strip('"').strip("'")
    return ""
