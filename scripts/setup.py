#!/usr/bin/env python3
"""Install development dependencies into this checkout, never the user's skills."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MIN_BUN = (1, 3, 14)


def run(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    print('+ ' + ' '.join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True, timeout=900)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-deps', action='store_true', help='also install Playwright OS dependencies; may require administrator access on Linux')
    parser.add_argument('--skip-browsers', action='store_true', help='install packages only; full rendering tests will still need matching browsers')
    parser.add_argument('--scope', choices=('all', 'book-poster'), default='all', help='book-poster installs only the portable Python renderer and browser')
    options = parser.parse_args()
    if sys.version_info < (3, 9):
        parser.error('Python 3.9 or newer is required')
    bun = shutil.which('bun')
    if options.scope == 'all':
        if not bun:
            parser.error('Bun 1.3.14 or newer is required; install it before running setup')
        version = subprocess.check_output([bun, '--version'], text=True).strip()
        try:
            parsed = tuple(int(part) for part in version.split('-', 1)[0].split('.')[:3])
        except ValueError:
            parser.error(f'Cannot parse Bun version: {version}')
        if parsed < MIN_BUN:
            parser.error(f'Bun >= 1.3.14 is required, found {version}')

    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    env['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.cache/ms-playwright')
    env['PLAYWRIGHT_SKIP_BROWSER_GC'] = '1'
    venv = ROOT / '.venv'
    python = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if venv.is_symlink():
        parser.error('Refusing to install into a symlinked .venv')
    if venv.exists() and not (venv / 'pyvenv.cfg').is_file():
        parser.error('.venv exists but is not a Python virtual environment')
    if not python.exists():
        run([sys.executable, '-m', 'venv', str(venv)], ROOT, env)
    requirements = ROOT / 'skills/ljg-book-poster/requirements.txt'
    run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(requirements)], ROOT, env)

    for manifest in sorted((ROOT / 'skills').glob('*/package.json')) if options.scope == 'all' else []:
        module = manifest.parent
        run([bun, 'install', '--frozen-lockfile', '--ignore-scripts'], module, env)
        cli = module / 'node_modules/playwright/cli.js'
        if cli.exists() and not options.skip_browsers:
            command = [bun, str(cli), 'install', 'chromium', '--only-shell']
            if options.with_deps:
                command.append('--with-deps')
            run(command, module, env)
    if not options.skip_browsers:
        command = [str(python), '-m', 'playwright', 'install', 'chromium', '--only-shell']
        if options.with_deps:
            command.append('--with-deps')
        run(command, ROOT, env)
    suffix = ' --scope book-poster' if options.scope == 'book-poster' else ''
    print('Dependencies installed in this checkout. Run: python3 scripts/check.py' + suffix)
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError) as error:
        print(f'Setup failed: {error}', file=sys.stderr)
        raise SystemExit(1)
