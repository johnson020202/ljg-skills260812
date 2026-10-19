#!/usr/bin/env python3
"""Fixed-viewport, device-budgeted PNG capture; all QA crops use the main PNG.

Exit: 0 clean, 1 blocking content, 2 render/resource failure. Default scale .75.
Outputs are built privately. POSIX publishes through a generation symlink;
Windows publishes regular files with ordinary-error rollback, not crash atomicity.
Public filenames stay unchanged. Failed builds keep the old set.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import io
import json
import math
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import unicodedata
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote, urlsplit

MAX_CAPTURE_DEVICE = 12000  # conservative budget, not a universal browser limit
MAX_IMAGE_PIXELS = 160_000_000
AUDIT_JS = Path(__file__).with_name('audit.js')
RESOURCE_TIMEOUT_MS = 15000
DEFAULT_SCALE = .75  # 1440 CSS px -> 1080 output px; not a layout transform
IS_WINDOWS = os.name == 'nt'


def configure_stdio(*streams):
    """CLI UTF-8 output, including redirected Windows streams; no import side effects."""
    for stream in streams or (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure:
            reconfigure(encoding='utf-8', errors='backslashreplace')


def windows_chromium_candidates():
    roots = [os.environ.get('ProgramFiles', r'C:\Program Files'),
             os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
             os.environ.get('LOCALAPPDATA')]
    return [str(Path(root) / vendor / product / 'Application' / executable)
            for root in roots if root
            for vendor, product, executable in (('Google', 'Chrome', 'chrome.exe'),
                                                ('Microsoft', 'Edge', 'msedge.exe'))]


def find_chromium() -> str | None:
    explicit = os.environ.get('CHROMIUM_PATH')
    if explicit:
        if not Path(explicit).is_file():
            raise ValueError(f'CHROMIUM_PATH not found: {explicit}')
        return explicit
    if os.environ.get('PLAYWRIGHT_BROWSERS_PATH'):
        return None  # CI selects the browser paired with its pinned Playwright.
    candidates = windows_chromium_candidates() if IS_WINDOWS else (
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome')
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


def serve(directory: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(2)
            super().setup()

        def handle(self):
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass  # disconnected/idle local clients, not resource success

        def log_message(self, *_args):
            pass

    class Server(http.server.ThreadingHTTPServer):
        daemon_threads = True
        block_on_close = False

    server = Server(('127.0.0.1', 0), lambda *a, **k: Quiet(*a, directory=str(directory), **k))
    threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True).start()
    return server


def validate_portable_components(path):
    # Win32 strips trailing dots/spaces from ordinary filename components. Refuse
    # these ambiguous spellings rather than allowing two outputs to alias. Anchors
    # (including UNC server/share) are not ordinary filename components.
    for component in path.parts:
        if component in (path.anchor, '.', '..'):
            continue
        if component.endswith(('.', ' ')):
            raise ValueError(f'Portable output component has trailing dot or space: {path}')


def output_path(path: Path) -> Path:
    # Resolve parents, never the published final symlink (that is an old generation).
    if IS_WINDOWS:
        validate_portable_components(path)
        reject_redirects(path)
    parent = path.absolute().parent.resolve()
    for ancestor in (parent, *parent.parents):
        if ancestor.name.startswith('.poster-') and (ancestor / 'owner').exists():
            raise ValueError(f'Output cannot be inside managed publication storage: {path}')
    return parent / path.name


def is_redirect(path):
    """Recognize Windows junctions/reparse points as well as ordinary symlinks."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def reject_redirects(path):
    for candidate in (path.absolute(), *path.absolute().parents):
        if is_redirect(candidate):
            raise ValueError(f'Redirected Windows output path: {candidate}')


def acquire_lock(path):
    if is_redirect(path):
        raise ValueError('Publication lock must not be a link or reparse point')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    lock = os.fdopen(fd, 'r+b', buffering=0)
    try:
        if IS_WINDOWS:
            import msvcrt
            if os.fstat(fd).st_size == 0:
                lock.write(b'\0')
            lock.seek(0)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise BlockingIOError('Another poster writer holds the publication lock') from error
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        lock.close()
        raise
    return lock  # closing the handle releases either platform lock


class OutputTransaction:
    """Single writer + staged generation + atomic pointer; never remove caller dirs.

    Existing regular outputs are retained under legacy-* on first migration.
    Only generations created by this class are cleaned on a subsequent success.
    Read/copy the bundle after publication; separate reads spanning a commit
    are not a snapshot. Legacy migration rolls back on ordinary exceptions,
    but its public aliases are installed one by one.
    """
    def __init__(self, paths, source, *, portable=None):
        self.portable = IS_WINDOWS if portable is None else portable
        if self.portable:
            for path in paths:
                validate_portable_components(path)
                if IS_WINDOWS:
                    reject_redirects(path)
        self.paths = [output_path(p) for p in paths]
        source = source.resolve()
        self.identities = {self.identity(path) for path in self.paths}
        if len(self.identities) != len(self.paths):
            raise ValueError('Output paths must be distinct')
        for target in self.paths:
            resolved = target.resolve()
            if (self.identity(target) in {self.identity(p) for p in (source, *source.parents)} or
                    resolved == source or resolved in source.parents or
                    (target.exists() and source.exists() and os.path.samefile(target, source))):
                raise ValueError(f'Output conflicts with input: {target}')
            if any(self.identity(target) in {self.identity(p) for p in other.parents} for other in self.paths):
                raise ValueError(f'Overlapping output paths: {target}')
        key = hashlib.sha256(self.identity(self.paths[0]).encode('utf-8')).hexdigest()[:16]
        self.root = self.paths[0].parent / ('.poster-' + key)
        self.stage = None
        self.lock = None

    def identity(self, path):
        # Portable publication conservatively treats case/NFC aliases as one
        # target, including when exercised on a POSIX test host. POSIX generation
        # hashes remain byte-for-byte compatible with existing published aliases.
        value = str(path)
        return unicodedata.normalize('NFC', value).casefold() if self.portable else value

    def __enter__(self):
        self.root.parent.mkdir(parents=True, exist_ok=True)
        if is_redirect(self.root):
            raise ValueError('Publication storage must not be a link or reparse point')
        fresh = not self.root.exists()
        self.root.mkdir(exist_ok=True)
        marker = self.root / 'owner'
        if fresh:
            marker.write_text('book-poster-output-v1\n', encoding='utf-8')
        if is_redirect(marker) or not marker.is_file() or marker.read_text(encoding='utf-8') != 'book-poster-output-v1\n':
            raise ValueError('Refusing unknown publication storage')
        self.lock = acquire_lock(self.root / 'lock')
        try:
            if self.portable:
                self.enter_portable()
                return self
            current = self.root / 'current'
            if current.exists() or current.is_symlink():
                if not current.is_symlink():
                    raise ValueError('Invalid publication pointer')
                link = os.readlink(current)
                generation = self.root / link
                if (Path(link).name != link or not link.startswith('generation-') or
                        generation.is_symlink() or not generation.is_dir()):
                    raise ValueError('Publication pointer escapes owned storage')
                if any(p.is_symlink() for p in generation.rglob('*')):
                    raise ValueError('Published generation contains unexpected symlinks')
            self.stage = Path(tempfile.mkdtemp(prefix='generation-', dir=self.root))
            for target in self.paths:
                if target.is_symlink():
                    expected = os.path.relpath(current / self.path(target).name, target.parent)
                    if os.readlink(target) != expected:
                        raise ValueError(f'Refusing unrelated output symlink: {target}')
                elif target.exists():
                    self.check_legacy(target)
        except BaseException:
            if self.stage:
                shutil.rmtree(self.stage, ignore_errors=True)
            self.lock.close()
            raise
        return self

    def enter_portable(self):
        # Ordinary files need no Windows symlink privileges. Never silently migrate
        # a POSIX pointer bundle, or overwrite backups left by an interrupted commit.
        if (self.root / 'current').exists() or is_redirect(self.root / 'current'):
            raise ValueError('Portable publication cannot replace a symlink-generation bundle')
        if any(self.root.glob('backup-*')):
            raise ValueError(f'Interrupted publication backup requires recovery: {self.root}')
        device = self.root.stat().st_dev
        for target in self.paths:
            if IS_WINDOWS:
                reject_redirects(target)
            if is_redirect(target):
                raise ValueError(f'Refusing redirected output: {target}')
            ancestor = target.parent
            while not ancestor.exists():
                parent = ancestor.parent
                if parent == ancestor:
                    raise ValueError(f'Output volume/root is unavailable: {target}')
                ancestor = parent
            if ancestor.stat().st_dev != device:
                raise ValueError('Portable publication outputs must be on the same volume')
            if target.exists():
                self.check_legacy(target, strict_manifest=True)
        self.stage = Path(tempfile.mkdtemp(prefix='generation-', dir=self.root))

    def commit_portable(self):
        """Exception rollback only: NOT multi-file or crash-atomic publication."""
        for target in self.paths:
            if not self.path(target).exists():
                raise ValueError(f'Missing staged output: {target}')
        backup_dir = Path(tempfile.mkdtemp(prefix='backup-', dir=self.root))
        changes = []
        try:
            for target in self.paths:
                if IS_WINDOWS:
                    reject_redirects(target)
                if is_redirect(target):
                    raise ValueError(f'Refusing redirected output: {target}')
                if target.exists():
                    self.check_legacy(target, strict_manifest=True)
                target.parent.mkdir(parents=True, exist_ok=True)
                backup = None
                if target.exists():
                    backup = backup_dir / self.path(target).name
                    os.replace(target, backup)
                change = [target, backup, False]
                changes.append(change)
                os.replace(self.path(target), target)
                change[2] = True
        except BaseException as error:
            restoration_errors = []
            for target, backup, installed in reversed(changes):
                try:
                    if installed:
                        if target.is_dir():
                            shutil.rmtree(target)
                        else:
                            target.unlink()
                    if backup is not None:
                        os.replace(backup, target)
                except OSError as rollback_error:
                    restoration_errors.append(str(rollback_error))
            if restoration_errors:
                # Backups are the last old copies: keep them and block another run.
                raise RuntimeError(f'Publication rollback incomplete; recover {backup_dir}: '
                                   + '; '.join(restoration_errors)) from error
            shutil.rmtree(backup_dir, ignore_errors=True)
            raise
        shutil.rmtree(backup_dir, ignore_errors=True)
        shutil.rmtree(self.stage, ignore_errors=True)
        self.stage = None

    @staticmethod
    def check_legacy(target, *, strict_manifest=False):
        # Migration accepts recognizable old outputs, never arbitrary caller data.
        from PIL import Image
        def png(path):
            with Image.open(path) as image:
                if image.format != 'PNG':
                    raise ValueError(f'Unknown existing output: {path}')
                image.verify()
        if target.is_dir():
            manifest = target / '_sections.json'
            if is_redirect(manifest) or not manifest.is_file() or not isinstance(json.loads(manifest.read_text(encoding='utf-8')), list):
                raise ValueError(f'Unknown existing output directory: {target}')
            if strict_manifest:
                listed = set()
                for section in json.loads(manifest.read_text(encoding='utf-8')):
                    if not isinstance(section, dict):
                        raise ValueError(f'Invalid section manifest: {manifest}')
                    name = section.get('file')
                    if name is None and isinstance(section.get('name'), str):
                        name = section['name'] + '.png'
                    if (not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name or
                            not name.endswith('.png') or name in listed):
                        raise ValueError(f'Invalid section manifest filename: {name}')
                    listed.add(name)
                actual = {entry.name for entry in target.iterdir() if entry != manifest}
                if actual != listed:
                    raise ValueError(f'Section manifest does not match files (missing or unlisted): {target}')
            for entry in target.iterdir():
                if entry == manifest:
                    continue
                if is_redirect(entry) or not entry.is_file() or entry.suffix != '.png':
                    raise ValueError(f'Unknown existing section output: {entry}')
                png(entry)
        else:
            try:
                png(target)
            except (OSError, ValueError):
                try:
                    audit = json.loads(target.read_text(encoding='utf-8'))
                    if not isinstance(audit, dict) or not all(k in audit for k in ('page', 'sections', 'counts')):
                        raise ValueError('not an audit')
                except (OSError, ValueError, UnicodeError) as error:
                    raise ValueError(f'Refusing unknown existing output: {target}') from error

    def path(self, target):
        target = output_path(target)
        identity = self.identity(target)
        if identity not in self.identities:
            raise ValueError(f'Undeclared output: {target}')
        suffix = self.identity(Path(target.suffix)) if self.portable and target.suffix else target.suffix
        name = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16] + suffix
        return self.stage / name

    def commit(self):
        if self.portable:
            return self.commit_portable()
        current = self.root / 'current'
        previous = current.resolve() if current.is_symlink() else None
        changes = []
        # Reserve an owned empty directory, not a predictable root/next path.
        pointer_dir = Path(tempfile.mkdtemp(prefix='pointer-', dir=self.root))
        pending = pointer_dir / 'next'
        try:
            for target in self.paths:
                if not self.path(target).exists():
                    raise ValueError(f'Missing staged output: {target}')
            # A caller may omit optional outputs on a later CLI invocation. Keep
            # their old aliases valid without copying pixel data unnecessarily.
            if previous:
                for old in previous.iterdir():
                    destination = self.stage / old.name
                    if destination.exists():
                        continue
                    if old.is_dir():
                        shutil.copytree(old, destination, copy_function=os.link)
                    else:
                        os.link(old, destination)
            for target in self.paths:
                staged = self.path(target)
                if not staged.exists():
                    raise ValueError(f'Missing staged output: {target}')
                target.parent.mkdir(parents=True, exist_ok=True)
                expected = os.path.relpath(current / staged.name, target.parent)
                if target.is_symlink():
                    if os.readlink(target) != expected:
                        raise ValueError(f'Refusing unrelated output symlink: {target}')
                    continue
                backup = None
                if target.exists():
                    backup = self.root / ('legacy-' + self.stage.name + '-' + staged.name)
                    os.replace(target, backup)
                changes.append((target, backup))
                target.symlink_to(expected, target_is_directory=staged.is_dir())
            pending.symlink_to(self.stage.name, target_is_directory=True)
            os.replace(pending, current)  # the generation commit point
        except BaseException:
            # Cleanup must never mask or prevent restoration of public outputs.
            for target, backup in reversed(changes):
                if target.is_symlink():
                    target.unlink()
                if backup:
                    os.replace(backup, target)
            raise
        finally:
            shutil.rmtree(pointer_dir, ignore_errors=True)
        self.stage = None
        # Publication already succeeded. Cleanup is best effort and narrowly owned.
        if previous and previous.parent == self.root and previous.name.startswith('generation-'):
            shutil.rmtree(previous, ignore_errors=True)

    def __exit__(self, *_args):
        if self.stage:
            shutil.rmtree(self.stage, ignore_errors=True)
        if self.lock:
            self.lock.close()


def validate_png(path, expected=None):
    """Decode staged bytes before publication, with the same explicit pixel budget."""
    import warnings
    from PIL import Image
    with warnings.catch_warnings():
        # Our budget is larger than Pillow's default warning threshold but lower
        # than its hard limit. Do not disable the explicit dimensions check.
        warnings.simplefilter('ignore', Image.DecompressionBombWarning)
        with Image.open(path) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError(f'PNG exceeds pixel budget: {path}')
            if expected and image.size != tuple(expected):
                raise ValueError(f'PNG dimensions changed: {path}')
            image.load()


def capture(cdp, y: float, h: float, width: int, scale: float):
    from PIL import Image
    data = cdp.send('Page.captureScreenshot', {
        'format': 'png', 'captureBeyondViewport': True,
        'clip': {'x': 0, 'y': y, 'width': width, 'height': h, 'scale': scale},
    })['data']
    with Image.open(io.BytesIO(base64.b64decode(data))) as im:
        return im.convert('RGB')


def page_height(page) -> int:
    return math.ceil(page.evaluate(
        'Math.max(document.body.scrollHeight, document.documentElement.scrollHeight,'
        "document.querySelector('#poster')?.scrollHeight || 0)"))


def prepare_page(page, url):
    """Observe actual resource requests, force lazy images, and fail visibly.

    Unused @font-face declarations are not loaded or treated as failures. Used
    font errors (including decode/OTS errors at HTTP 200) remain fatal. No blanket
    suppression of font console messages. Only loopback resources are allowed.
    """
    failures = []
    origin = urlsplit(url)

    def route_resource(route):
        parsed = urlsplit(route.request.url)
        if parsed.scheme in ('data', 'blob', 'about') or (
                parsed.scheme == origin.scheme and parsed.netloc == origin.netloc):
            route.continue_()
        else:
            failures.append('external resource blocked: ' + route.request.url)
            route.abort()

    page.route('**/*', route_resource)
    page.on('requestfailed', lambda req: failures.append(f'{req.resource_type} {req.url}: {req.failure}'))
    page.on('response', lambda res: failures.append(f'HTTP {res.status} {res.url}') if res.status >= 400 else None)
    page.on('pageerror', lambda err: failures.append('page script: ' + str(err)))
    response = page.goto(url, wait_until='load', timeout=RESOURCE_TIMEOUT_MS)
    if response is None or not response.ok:
        raise RuntimeError(f'HTTP {response.status if response else "no response"}: {url}')
    page.add_style_tag(content='[data-export-ignore]{display:none!important} '
                               '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}')
    page.evaluate('''() => {
      document.getAnimations().forEach(a => a.pause());
      document.querySelectorAll('img').forEach(img => { img.loading = 'eager'; });
    }''')
    resources = page.evaluate('''async (timeout) => {
      let timer;
      try {
        return await Promise.race([
          (async () => {
            const images = await Promise.all([...document.images].map(async img => {
              try { await img.decode(); return null; }
              catch (e) { return `image ${img.currentSrc || img.src}: ${e}`; }
            }));
            await document.fonts.ready;
            const fonts = [...document.fonts].filter(f => f.status === 'error')
              .map(f => `font ${f.family} (${f.style} ${f.weight}): ${f.status}`);
            return [...images.filter(Boolean), ...fonts];
          })(),
          new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('RESOURCE timeout')), timeout); })
        ]);
      } finally { clearTimeout(timer); }
    }''', RESOURCE_TIMEOUT_MS)
    failures.extend(resources)
    # Flush pending browser events without a fixed sleep.
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    if failures:
        raise RuntimeError('RESOURCE failure:\n' + '\n'.join(dict.fromkeys(failures)))


def build(html, out, width, scale, audit_out, slice_dir):
    """Build only, at private paths. Exactly one audit, K browser captures."""
    from playwright.sync_api import sync_playwright
    from PIL import Image

    if not html.is_file():
        raise ValueError(f'Input HTML not found: {html}')
    if width <= 0 or not math.isfinite(scale) or scale <= 0 or width * scale > MAX_CAPTURE_DEVICE:
        raise ValueError('width/scale must be positive, finite and within the device-pixel budget')
    server = serve(html.parent)
    t0 = time.monotonic()
    main = None
    try:
        with sync_playwright() as p:
            launch = {'headless': True, 'args': ['--no-sandbox', '--hide-scrollbars', '--force-color-profile=srgb']}
            chromium = find_chromium()
            if chromium:
                launch['executable_path'] = chromium
            with p.chromium.launch(**launch) as browser:
                page = browser.new_page(viewport={'width': width, 'height': 1200}, device_scale_factor=1,
                                        service_workers='block')
                prepare_page(page, f'http://127.0.0.1:{server.server_address[1]}/{quote(html.name, safe="")}')
                total = page_height(page)
                wpx, hpx = math.floor(width * scale), math.floor(total * scale)
                # Chromium floors fractional CSS clips before scaling. Use integer
                # CSS boundaries that also land on device pixels, then crop the
                # final part only. Common CLI scales (1.25/1.5/2/3) are exact.
                fraction = Fraction(str(scale)).limit_denominator(1000)
                quantum = fraction.denominator
                if abs(float(fraction) - scale) > 1e-9:
                    raise ValueError('scale must be representable with <=1000 fractional steps')
                css_step = (math.floor(MAX_CAPTURE_DEVICE / scale) // quantum) * quantum
                if css_step <= 0:
                    raise ValueError('scale exceeds aligned capture budget')
                if total < 10 or min(wpx, hpx) < 1 or wpx * hpx > MAX_IMAGE_PIXELS:
                    raise ValueError(f'Page dimensions exceed render budget: {wpx}x{hpx}')
                t_audit = time.monotonic()
                info = page.evaluate(AUDIT_JS.read_text(encoding='utf-8'))
                audit_s = time.monotonic() - t_audit
                cdp = page.context.new_cdp_session(page)
                main = Image.new('RGB', (wpx, hpx), 'white')
                t_cap = time.monotonic()
                captures = 0
                for y in range(0, total, css_step):
                    css_h = min(css_step, total - y)
                    top = round(y * scale)
                    height = min(round(css_h * scale), hpx - top)
                    part = capture(cdp, y, css_h, width, scale)
                    try:
                        if part.width != wpx or part.height < height or part.height > height + 1:
                            raise RuntimeError(f'Capture size mismatch: {part.size} != {(wpx, height)}')
                        main.paste(part, (0, top))
                    finally:
                        part.close()
                    captures += 1
                cap_s = time.monotonic() - t_cap
                if page_height(page) != total:
                    raise RuntimeError('Page layout changed during capture')
    except BaseException:
        if main:
            main.close()
        raise
    finally:
        server.shutdown()
        server.server_close()

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        main.save(out, 'PNG')
        validate_png(out, (wpx, hpx))
        if slice_dir:
            slice_dir.mkdir(parents=True, exist_ok=True)
            for sec in info['sections']:
                top = max(0, math.floor((sec['y'] - 12) * scale))
                bottom = min(hpx, math.ceil((sec['bottom'] + 12) * scale))
                if bottom <= top:
                    raise ValueError(f'Invalid section coordinates: {sec["name"]}')
                sec['file'] = sec['name'] + '.png'
                sec['cropPixels'] = [0, top, wpx, bottom]
                with main.crop(sec['cropPixels']) as crop:
                    crop.save(slice_dir / sec['file'], 'PNG')
                validate_png(slice_dir / sec['file'], (wpx, bottom - top))
            (slice_dir / '_sections.json').write_text(json.dumps(info['sections'], ensure_ascii=False, indent=1), encoding='utf-8')
        info['render'] = {'scale': scale, 'size': [wpx, hpx], 'auditPasses': 1, 'captureCalls': captures,
                          'deviceSliceBudget': MAX_CAPTURE_DEVICE}
        if audit_out:
            audit_out.parent.mkdir(parents=True, exist_ok=True)
            audit_out.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
        return {'png': str(out), 'size': [wpx, hpx], 'cssHeight': total, 'slices': captures,
                'auditPasses': 1, 'auditSeconds': round(audit_s, 3), 'captureSeconds': round(cap_s, 3),
                'totalSeconds': round(time.monotonic() - t0, 3), 'blockingIssues': info['counts']['1']}
    finally:
        if main:
            main.close()


def render(html, out, width, scale, audit_out, slice_dir, sheet=None):
    from contact_sheet import from_sections
    if sheet and not slice_dir:
        raise ValueError('--sheet requires --slices')
    paths = [p for p in (out, audit_out, slice_dir, sheet) if p is not None]
    with OutputTransaction(paths, html) as tx:
        staged = lambda path: tx.path(path) if path is not None else None
        result = build(html.resolve(), staged(out), width, scale, staged(audit_out), staged(slice_dir))
        if sheet:
            from_sections(staged(slice_dir), staged(sheet))
            validate_png(staged(sheet))
        tx.commit()
    result['png'] = str(out)
    print(json.dumps(result))
    return result


def main():
    configure_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument('input_html', type=Path)
    ap.add_argument('output_png', type=Path)
    ap.add_argument('--width', type=int, default=1440)
    ap.add_argument('--scale', type=float, default=DEFAULT_SCALE, help='output pixels per CSS px (default .75: 1080px at width 1440)')
    ap.add_argument('--audit', type=Path)
    ap.add_argument('--slices', type=Path)
    ap.add_argument('--sheet', type=Path)
    args = ap.parse_args()
    try:
        result = render(args.input_html.resolve(), output_path(args.output_png), args.width, args.scale,
                        output_path(args.audit) if args.audit else None,
                        output_path(args.slices) if args.slices else None,
                        output_path(args.sheet) if args.sheet else None)
    except Exception as error:
        print(f'RENDER FAILED: {error}', file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(1 if result['blockingIssues'] else 0)


if __name__ == '__main__':
    main()
