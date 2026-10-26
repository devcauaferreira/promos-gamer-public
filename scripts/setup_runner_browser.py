"""Valida o Chrome já instalado no runner e compartilha seu caminho entre etapas."""
import os
from pathlib import Path
import re
import shutil
import subprocess

BROWSER_NAMES = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser')
VERSION = re.compile(r'^(Google Chrome(?: for Testing)?|Chromium)\s+(\d+(?:\.\d+){1,3})(?:\s|$)')


def local_file(value, label):
    if (not isinstance(value, str) or not value or '://' in value
            or any(character in value for character in '\r\n\x00')):
        raise ValueError(label + ' inválido.')
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise ValueError(label + ' precisa ser um arquivo local absoluto existente.')
    return path.resolve(strict=True)


def setup_runner_browser(env=None, which=None, run=None):
    env = os.environ if env is None else env
    if env.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Este auxiliar só pode configurar um runner GitHub Actions.')
    target = local_file(env.get('GITHUB_ENV', ''), 'Arquivo de ambiente do runner')
    which = which or shutil.which
    run = run or subprocess.run
    for name in BROWSER_NAMES:
        candidate = which(name)
        if not candidate:
            continue
        executable = local_file(candidate, 'Executável do navegador')
        try:
            result = run([str(executable), '--version'], capture_output=True, text=True,
                         timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            continue
        version = VERSION.match(result.stdout.strip()) if result.returncode == 0 else None
        if version is None:
            continue
        assignments = {'PLAYWRIGHT_BROWSER_PATH': str(executable),
                       'WHATSAPP_BROWSER_PATH': str(executable),
                       'PUPPETEER_SKIP_DOWNLOAD': 'true'}
        with target.open('a', encoding='utf-8', newline='\n') as output:
            for key, value in assignments.items():
                output.write(key + '=' + value + '\n')
        print('Navegador pré-instalado confirmado: ' + version.group(1) + ' ' + version.group(2), flush=True)
        return str(executable)
    raise RuntimeError('Nenhum Chrome/Chromium pré-instalado foi confirmado; não haverá instalação automática.')


if __name__ == '__main__':
    try:
        setup_runner_browser()
    except (ValueError, RuntimeError, OSError):
        raise SystemExit('Falha ao validar navegador pré-instalado ou ambiente do runner; nenhum download foi iniciado.')
