#!/usr/bin/env python3
"""Run repository contracts and all checked-in regression suites without publishing."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'https://github.com/johnson020202/ljg-skills260812'
EXCLUDED = {'.git', '.cache', '.venv', '__pycache__', 'node_modules'}


def source_files(root: Path) -> list[Path]:
    result = []
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name not in EXCLUDED and not (Path(directory) / name).is_symlink())
        result.extend(Path(directory) / name for name in sorted(files))
    return result


def contract_errors(root: Path) -> list[str]:
    errors = []
    skill_dirs = sorted(path for path in (root / 'skills').iterdir() if path.is_dir())
    skills = {path.name for path in skill_dirs if (path / 'SKILL.md').is_file()}
    if not skills:
        errors.append('No skills found')
    readme = (root / 'README.md').read_text(encoding='utf-8')
    listed = set(re.findall(r'^\|\s*\*\*((?:ljg-[a-z0-9-]+|fix-ljg-org-to-md))\*\*\s*\|', readme, re.MULTILINE))
    if skills != listed:
        errors.append(f'README skill inventory mismatch: missing={sorted(skills - listed)}, unknown={sorted(listed - skills)}')
    if re.search(r'(?:skills add |github\.com/)lijigang/ljg-skills(?:\.git|[\s#])', readme):
        errors.append('README install instructions still point at the upstream repository')
    for path in skill_dirs:
        definition = path / 'SKILL.md'
        if not definition.is_file():
            errors.append(f'{path.name}: missing SKILL.md')
            continue
        match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)', definition.read_text(encoding='utf-8'), re.DOTALL)
        if not match:
            errors.append(f'{path.name}: missing frontmatter')
            continue
        name = re.search(r'^name:\s*[\"\']?([a-z0-9-]+)[\"\']?\s*$', match.group(1), re.MULTILINE)
        if not name or name.group(1) != path.name:
            errors.append(f'{path.name}: frontmatter name must match directory')
        if not re.search(r'^description:\s*\S', match.group(1), re.MULTILINE):
            errors.append(f'{path.name}: missing description')
    try:
        plugin = json.loads((root / '.claude-plugin/plugin.json').read_text())
        market = json.loads((root / '.claude-plugin/marketplace.json').read_text())
        versions = [plugin['version'], market['version'], *[entry['version'] for entry in market['plugins']]]
        if not versions or len(set(versions)) != 1 or not re.fullmatch(r'\d+\.\d+\.\d+', versions[0]):
            errors.append(f'Plugin versions must agree: {versions}')
        for name, manifest in [('plugin', plugin), ('marketplace', market)]:
            if manifest.get('repository') != REPOSITORY:
                errors.append(f'{name}: repository must be {REPOSITORY}')
    except (KeyError, TypeError, ValueError) as error:
        errors.append(f'Invalid plugin metadata: {error}')
    return errors


def suite_name(prefix: str, relative_path) -> str:
    return prefix + '-' + '-'.join(relative_path.parts)


def execute(name: str, command: list[str], env: dict[str, str], timeout: int, log_dir: Path) -> dict:
    started = time.monotonic()
    print(f'\n== {name} ==', flush=True)
    log = log_dir / f'{name}.log'
    with log.open('w', encoding='utf-8') as output:
        try:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=os.name != 'nt')
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                output.write(f'\nTIMEOUT after {timeout}s\n')
                code = 124
        except OSError as error:
            output.write(f'{error}\n')
            code = 127
    text = log.read_text(encoding='utf-8', errors='replace')
    print(text[-12000:], end='' if text.endswith('\n') else '\n', flush=True)
    if len(text) > 12000:
        print(f'Full output: {log}', flush=True)
    elapsed = round(time.monotonic() - started, 3)
    print(f'{name}: {"PASS" if code == 0 else "FAIL"} ({elapsed}s)', flush=True)
    return {'name': name, 'command': command, 'exitCode': code, 'seconds': elapsed, 'log': str(log.relative_to(ROOT))}


def verify_formats(options) -> int:
    from build_format import build

    (ROOT / '.cache/format-check-results.json').write_text(json.dumps({'status': 'incomplete', 'scope': 'formats-not-finished', 'checks': []}) + '\n', encoding='utf-8')
    runtime_root = Path(options.runtime_root).resolve() if options.runtime_root else ROOT
    python = options.python or str(runtime_root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
    if not Path(python).is_file():
        python = sys.executable
    checks = []
    formats = ['source', 'md'] if options.format == 'all' else [options.format]
    workspace = Path(tempfile.mkdtemp(prefix='format-check-', dir=ROOT / '.cache'))
    for format_name in formats:
        target = ROOT if format_name == 'source' else workspace / format_name
        if format_name != 'source':
            build(ROOT, target, format_name)
            for manifest in sorted((target / 'skills').glob('*/package.json')) if not options.static else []:
                dependencies = runtime_root / 'skills' / manifest.parent.name / 'node_modules'
                if not dependencies.is_dir():
                    raise ValueError(f'Missing dependencies for {manifest.parent.name}; run scripts/setup.py first')
                (manifest.parent / 'node_modules').symlink_to(dependencies, target_is_directory=True)
        command = [sys.executable, str(target / 'scripts/check.py'), '--format', 'current', '--python', python,
                   '--runtime-root', str(runtime_root), '--timeout', str(options.timeout)]
        if options.static:
            command.append('--static')
        print(f'\n== Verify {format_name} distribution ==', flush=True)
        result = subprocess.run(command, cwd=target, timeout=options.timeout * 20)
        child_path = target / '.cache/check-results.json'
        child = json.loads(child_path.read_text(encoding='utf-8')) if child_path.is_file() else {'status': 'incomplete'}
        checks.append({'format': format_name, 'exitCode': result.returncode, 'directory': str(target), 'report': child})
        (ROOT / '.cache/check-results.json').write_text(json.dumps({'status': 'incomplete', 'scope': 'formats-not-finished', 'checks': checks}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    failed = [entry['format'] for entry in checks if entry['exitCode'] or entry['report'].get('status') != 'pass']
    report = {'status': 'fail' if failed else 'pass', 'scope': 'formats-static' if options.static else 'formats-full',
              'formats': formats, 'failed': failed, 'checks': checks}
    (ROOT / '.cache/format-check-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (ROOT / '.cache/check-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'\nFormat checks: {report["status"].upper()}; report: {ROOT / ".cache/format-check-results.json"}')
    return int(bool(failed))


def main() -> int:
    report_path = ROOT / '.cache/check-results.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({'status': 'incomplete', 'scope': 'not-finished', 'checks': []}) + '\n', encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--static', action='store_true', help='contracts and syntax only; does not claim regression tests passed')
    parser.add_argument('--format', choices=('current', 'source', 'md', 'all'), default='current', help='verify this checkout, or build and verify explicit format distributions')
    parser.add_argument('--scope', choices=('all', 'book-poster'), default='all', help='book-poster runs the portable renderer suite only, not all repository tests')
    parser.add_argument('--runtime-root', help='reuse dependencies and matching browsers from this prepared checkout')
    parser.add_argument('--python', help='Python interpreter for tests; defaults to the checkout virtual environment')
    parser.add_argument('--timeout', type=int, default=600, help='timeout in seconds for each test suite')
    options = parser.parse_args()
    if options.timeout <= 0:
        parser.error('--timeout must be positive')
    if options.scope != 'all' and options.format != 'current':
        parser.error('--scope book-poster must use --format current')
    if options.format != 'current':
        return verify_formats(options)
    runtime_root = Path(options.runtime_root).resolve() if options.runtime_root else ROOT
    log_dir = ROOT / '.cache/check'
    log_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPYCACHEPREFIX=str(ROOT / '.cache/pycache'), PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    env['PLAYWRIGHT_BROWSERS_PATH'] = str(runtime_root / '.cache/ms-playwright')
    env.pop('CHROMIUM_PATH', None)
    files = source_files(ROOT)
    errors = contract_errors(ROOT)
    for path in files:
        if path.suffix == '.py':
            try:
                compile(path.read_bytes(), str(path), 'exec')
            except (SyntaxError, ValueError) as error:
                errors.append(f'{path.relative_to(ROOT)}: {error}')
    results = [{'name': 'repository-contracts-and-python-syntax', 'exitCode': int(bool(errors)), 'errors': errors}]
    print('\n'.join(errors) if errors else 'Repository contracts and Python syntax: PASS', flush=True)
    shell = shutil.which('bash')
    for path in files:
        if path.suffix == '.sh' and options.scope == 'all':
            results.append(execute(suite_name('shell', path.relative_to(ROOT)), [shell or 'bash', '-n', str(path)], env, options.timeout, log_dir))
    if not options.static:
        venv_python = runtime_root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        python = options.python or (str(venv_python) if venv_python.is_file() else sys.executable)
        bun = shutil.which('bun') or 'bun'
        for module in sorted((ROOT / 'skills').iterdir()):
            tests = [path for path in files if path.name.endswith('.test.ts') and module in path.parents]
            if tests and options.scope == 'all':
                results.append(execute(module.name + '-tests', [bun, 'test', '--no-install', '--timeout', '120000', *[str(path) for path in tests]], env, options.timeout, log_dir))
        python_dirs = sorted({path.parent for path in files if path.name.startswith('test_') and path.suffix == '.py'})
        for directory in python_dirs:
            if options.scope == 'book-poster' and directory != ROOT / 'skills/ljg-book-poster/scripts':
                continue
            name = suite_name('python', directory.relative_to(ROOT))
            results.append(execute(name, [python, '-m', 'unittest', 'discover', '-s', str(directory), '-p', 'test_*.py', '-v'], env, options.timeout, log_dir))
        for name, command in [
            ('card-audit', [bun, '--no-install', 'skills/ljg-card/assets/audit.ts']),
            ('present-self-test', [bun, '--no-install', 'skills/ljg-present/Tools/ValidateDeck.ts', '--self-test']),
        ]:
            if options.scope == 'all':
                results.append(execute(name, command, env, options.timeout, log_dir))
    failed = [entry['name'] for entry in results if entry['exitCode'] != 0]
    report = {'status': 'fail' if failed else 'pass', 'scope': ('static-only' if options.static else 'full') if options.scope == 'all' else ('book-poster-static-only' if options.static else 'book-poster-only'), 'failed': failed, 'checks': results}
    (ROOT / '.cache/check-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'\n{report["scope"]}: {report["status"].upper()}; report: {ROOT / ".cache/check-results.json"}')
    return int(bool(failed))


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Check failed: {error}', file=sys.stderr)
        raise SystemExit(1)
