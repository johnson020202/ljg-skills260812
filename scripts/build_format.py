#!/usr/bin/env python3
"""Build a complete offline Org/Markdown distribution in a new directory."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import unicodedata

ROOT_PATHS = ('README.md', 'CLAUDE.md', 'LICENSE', '.gitignore', 'scripts', 'docs', '.github')
METADATA = ('.claude-plugin/plugin.json', '.claude-plugin/marketplace.json')
MANIFEST = '.format-build.json'
EXCLUDED = {'.git', '.cache', '.venv', 'node_modules', '__pycache__', '.DS_Store', '.lcode', 'test-results', 'playwright-report'}


def excluded(name: str) -> bool:
    return name in EXCLUDED or name.endswith(('.pyc', '.pyo', '.log', '.pem', '.key')) or name == '.env' or (name.startswith('.env.') and name not in {'.env.example', '.env.sample'})


def collect(source: Path) -> dict[str, tuple[str, bytes]]:
    tree = {}
    for relative in (*ROOT_PATHS, *METADATA, 'skills'):
        path = source / relative
        if path.is_symlink():
            raise ValueError(f'Symlinked distribution input: {relative}')
        if not path.exists():
            if relative in ('skills', 'README.md', *METADATA):
                raise ValueError(f'Missing distribution input: {relative}')
            continue
        if path.is_file():
            paths = [path]
        else:
            paths = []
            def fail(error):
                raise error
            for directory, names, files in os.walk(path, followlinks=False, onerror=fail):
                names[:] = sorted(name for name in names if not excluded(name))
                for name in names:
                    if (Path(directory) / name).is_symlink():
                        raise ValueError(f'Symlinked distribution directory: {Path(directory) / name}')
                paths.extend(Path(directory) / name for name in sorted(files) if not excluded(name))
        for item in paths:
            info = item.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f'Non-regular distribution input: {item}')
            name = item.relative_to(source).as_posix()
            tree[name] = ('100755' if info.st_mode & 0o111 else '100644', item.read_bytes())
    return tree


def path_key(path: Path | str) -> tuple[str, ...]:
    return tuple(unicodedata.normalize('NFC', part).casefold() for part in Path(path).parts)


def validate_tree_paths(tree: dict[str, tuple[str, bytes]]) -> None:
    aliases = {}
    for path in tree:
        key = path_key(path)
        if key in aliases:
            raise ValueError(f'Output path alias collision: {aliases[key]} / {path}')
        aliases[key] = path
    for key, path in aliases.items():
        if any(key[:end] in aliases for end in range(1, len(key))):
            raise ValueError('File/directory output collision: ' + path)


def fingerprint(tree: dict[str, tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for path, (mode, data) in sorted(tree.items()):
        digest.update(path.encode('utf-8') + b'\0' + mode.encode('ascii') + b'\0')
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def converter(source: Path):
    path = source / 'skills/ljg-push/Tools/markdown.py'
    spec = importlib.util.spec_from_file_location('ljg_format_converter', path)
    if spec is None or spec.loader is None:
        raise ValueError('Cannot load the repository format converter')
    module = importlib.util.module_from_spec(spec)
    old = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old
    return module.mdize


def build(source: Path, output: Path, format_name: str) -> dict:
    if format_name not in ('org', 'md'):
        raise ValueError('format must be org or md')
    if source.is_symlink():
        raise ValueError('Source must not be a symlink')
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError('Source must be a directory')
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Output must be a new directory; existing content is never replaced')
    for ancestor in output.parents:
        if ancestor.is_symlink():
            raise ValueError('Output parent must not be a symlink')
    output = output.parent.resolve() / output.name
    output_key, source_key = path_key(output), path_key(source)
    if source_key[:len(output_key)] == output_key:
        raise ValueError('Output overlaps the source directory')
    for relative in (*ROOT_PATHS, *METADATA, 'skills'):
        included = source / relative
        included_key = path_key(included)
        if output_key[:len(included_key)] == included_key:
            raise ValueError('Output cannot be placed inside distribution inputs')
    existing = source / MANIFEST
    if existing.exists():
        if existing.is_symlink():
            raise ValueError('Invalid source format manifest')
        source_format = json.loads(existing.read_text(encoding='utf-8')).get('format')
        if source_format == 'md' and format_name == 'org':
            raise ValueError('Cannot reconstruct Org sources from a Markdown distribution; use the original source')
    before = collect(source)
    validate_tree_paths(before)
    result = dict(before)
    if format_name == 'md':
        skills = {path[len('skills/'):]: value for path, value in before.items() if path.startswith('skills/')}
        converted = converter(source)(skills)
        result = {path: value for path, value in before.items() if not path.startswith('skills/')}
        for path, value in converted.items():
            parts = PurePosixPath(path).parts
            if not parts or PurePosixPath(path).is_absolute() or any(part in ('.', '..') for part in parts) or '\\' in path:
                raise ValueError('Unsafe converted path: ' + path)
            result['skills/' + path] = value
    validate_tree_paths(result)
    if fingerprint(collect(source)) != fingerprint(before):
        raise ValueError('Distribution inputs changed during conversion')
    manifest = {
        'schemaVersion': 1,
        'format': format_name,
        'sourceFingerprint': fingerprint(before),
        'outputFingerprint': fingerprint(result),
        'skills': sorted({PurePosixPath(path).parts[1] for path in result if path.startswith('skills/') and path.endswith('/SKILL.md')}),
        'files': [{'path': path, 'mode': mode, 'sha256': hashlib.sha256(data).hexdigest()} for path, (mode, data) in sorted(result.items())],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + output.name + '-build-', dir=output.parent))
    try:
        for path, (mode, data) in result.items():
            destination = staging / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(data)
            destination.chmod(0o755 if mode == '100755' else 0o644)
            if destination.read_bytes() != data:
                raise OSError('Output readback mismatch: ' + path)
        written = collect(staging)
        if written.keys() != result.keys() or any(written[path][1] != result[path][1] for path in result):
            raise OSError('Staged distribution does not match the output manifest')
        if os.name != 'nt' and any(written[path][0] != result[path][0] for path in result):
            raise OSError('Staged file modes do not match the output manifest')
        (staging / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if output.exists() or output.is_symlink():
            raise ValueError('Output appeared during build; refusing replacement')
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--format', choices=('org', 'md'), default='md')
    options = parser.parse_args()
    try:
        result = build(options.source, options.output, options.format)
    except (OSError, ValueError, ImportError) as error:
        print(f'BUILD FAILED: {error}', file=sys.stderr)
        return 1
    print(json.dumps({'status': 'built', 'format': result['format'], 'output': str(options.output.absolute()), 'skills': len(result['skills']), 'files': len(result['files']), 'sha256': result['outputFingerprint']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
