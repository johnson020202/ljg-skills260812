#!/usr/bin/env python3
"""Offline renderer regressions. All writes, corrupt fonts and sockets use tempdirs.

Run: python3 -m unittest discover -s skills/ljg-book-poster/scripts -p 'test_*.py'
Fixtures reproduce REN-01..08 from the 2026-10-19 audit; no external driver.
"""
from __future__ import annotations

import contextlib
import hashlib
import http.client
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

from PIL import Image, ImageChops

import contact_sheet
import render_png

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / 'scripts'


def document(content='正常正文', css='', section=''):
    return ('<meta charset="utf-8"><style>*{box-sizing:border-box;margin:0}'
            'html,body{background:white;color:black;font:70px/1.4 sans-serif}'
            '#poster{width:1440px;padding:40px}section{margin-bottom:80px;min-height:1300px}'
            'section:last-child{margin-bottom:0}' + css + '</style><main id="poster">'
            '<section ' + section + '>' + content + '</section></main>')


def snapshot(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}


class TempTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='poster-regression-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def html(self, text=None, name='book.html'):
        p = self.root / name
        p.write_text(document() if text is None else text, encoding='utf-8')
        return p

    def render(self, html, scale=1, sections=True):
        output = self.root / 'out'
        with contextlib.redirect_stdout(io.StringIO()):
            return render_png.render(html, output / 'book.png', 1440, scale,
                                     output / 'audit.json', output / 'sections' if sections else None)

    def cli(self, html, *args, script='poster.py'):
        cmd = [sys.executable, str(SCRIPTS / script), str(html)]
        if script == 'poster.py':
            cmd += ['--outdir', str(self.root / 'out'), '--scale', '1']
        else:
            cmd += [str(self.root / 'out' / 'book.png'), '--scale', '1']
        return subprocess.run(cmd + list(args), encoding='utf-8', capture_output=True, timeout=60)


class RenderTests(TempTests):
    def test_v33_default_delivery_explicit_scale_and_thumbnail_sizes(self):
        html = self.html(name='中文书名.html')
        for script in ('poster.py', 'render_png.py'):
            for flags, expected in (([], 1080), (['--scale', '2'], 2880),
                                    (['--width', '1600', '--scale', '.75'], 1200)):
                with self.subTest(script=script, flags=flags):
                    html.write_text(document(css='#poster{width:1600px}' if '--width' in flags else ''), encoding='utf-8')
                    output = self.root / script.replace('.py', '')
                    command = [sys.executable, str(SCRIPTS / script), str(html)]
                    if script == 'poster.py':
                        command += ['--outdir', str(output)]
                        png = output / '中文书名.png'
                    else:
                        png = output / 'book.png'
                        command += [str(png)]
                    result = subprocess.run(command + flags, capture_output=True,
                                            encoding='utf-8', timeout=60)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    with Image.open(png) as image:
                        self.assertEqual(image.width, expected)
                    if script == 'poster.py':
                        with Image.open(output / '中文书名-thumb.png') as thumbnail:
                            self.assertEqual(thumbnail.width, 440)
                        audit = json.loads((output / '中文书名-audit.json').read_text(encoding='utf-8'))
                        self.assertEqual(audit['minFontPx'], 70)
                        self.assertEqual(audit['underFloorPx'], 0)

    def test_v33_three_quarter_scale_across_slice_boundary(self):
        html = self.html(document('<p>开始</p><p style="position:absolute;bottom:0">结束</p>',
                                 section='data-name="长章" style="height:17003px;background:#ccddff;position:relative"'))
        stats = self.render(html, .75)
        self.assertEqual(stats['size'], [1080, int(stats['cssHeight'] * .75)])
        self.assertGreater(stats['slices'], 1)
        with Image.open(self.root / 'out/book.png') as main:
            section = json.loads((self.root / 'out/sections/_sections.json').read_text(encoding='utf-8'))[0]
            with Image.open(self.root / 'out/sections' / section['file']) as crop:
                self.assertIsNone(ImageChops.difference(crop, main.crop(section['cropPixels'])).getbbox())
            for y in (11999, 12000, 12001):
                self.assertEqual(main.getpixel((750, y)), (204, 221, 255))

    def test_tall_sections_equal_main_and_scale_budget(self):
        html = self.html(document('<p>开始</p><p style="position:absolute;bottom:0">结束</p>',
                                 section='data-name="tall" style="height:9000px;background:linear-gradient(#fdd,#ddf);position:relative"'))
        original = render_png.capture
        for scale in (2, 3):
            with self.subTest(scale=scale), patch.object(render_png, 'capture', wraps=original) as captured:
                stats = self.render(html, scale)
                self.assertTrue(all(call.args[2] * scale <= 12000 for call in captured.call_args_list))
                self.assertEqual(stats['auditPasses'], 1)
                self.assertEqual(captured.call_count, stats['slices'])
                with Image.open(self.root / 'out/book.png') as main:
                    manifest = json.loads((self.root / 'out/sections/_sections.json').read_text(encoding='utf-8'))
                    for sec in manifest:
                        with Image.open(self.root / 'out/sections' / sec['file']) as crop:
                            self.assertIsNone(ImageChops.difference(crop, main.crop(sec['cropPixels'])).getbbox())
                    # Independent sentinels: no white band/restarted gradient near the old cap.
                    for css_y in (5500, 5700, 6050, 8800):
                        red, green, blue = main.getpixel((1000 * scale, css_y * scale))
                        self.assertLess(red, 240)
                        self.assertLess(green, 225)
                        self.assertGreater(blue, 238)

    def test_one_real_dom_audit_supplies_manifest_and_report(self):
        from playwright.sync_api import Page
        original = Page.evaluate
        audit_source = render_png.AUDIT_JS.read_text(encoding='utf-8')
        calls = []
        def evaluate(page, expression, *args, **kwargs):
            if expression == audit_source:
                calls.append(expression)
            return original(page, expression, *args, **kwargs)
        with patch.object(Page, 'evaluate', autospec=True, side_effect=evaluate):
            self.render(self.html())
        self.assertEqual(len(calls), 1)
        audit = json.loads((self.root / 'out/audit.json').read_text(encoding='utf-8'))
        sections = json.loads((self.root / 'out/sections/_sections.json').read_text(encoding='utf-8'))
        self.assertEqual(audit['sections'], sections)

    def test_fractional_scale_has_exact_main_crop_coordinates(self):
        self.render(self.html(document(section='style="height:1300.5px"')), 1.25)
        with Image.open(self.root / 'out/book.png') as main:
            sec = json.loads((self.root / 'out/sections/_sections.json').read_text(encoding='utf-8'))[0]
            with Image.open(self.root / 'out/sections' / sec['file']) as crop:
                self.assertIsNone(ImageChops.difference(crop, main.crop(sec['cropPixels'])).getbbox())

    def test_renamed_sections_do_not_keep_stale_files(self):
        html = self.html(document(section='data-name="old-title"'))
        self.render(html)
        html.write_text(document(section='data-name="new-title"'), encoding='utf-8')
        self.render(html)
        directory = self.root / 'out/sections'
        self.assertEqual([p.name for p in directory.glob('*.png')], ['01-new-title.png'])

    def test_section_name_cannot_escape_output(self):
        self.render(self.html(document(section='data-name="../escape/../../outside"')))
        sections = self.root / 'out/sections'
        manifest = json.loads((sections / '_sections.json').read_text(encoding='utf-8'))
        self.assertEqual(len(list(sections.glob('*.png'))), 1)
        self.assertNotIn('/', manifest[0]['file'])

    def test_missing_or_corrupt_used_resources_fail_preserving_previous_outputs(self):
        html = self.html()
        self.assertEqual(self.cli(html).returncode, 0)
        before = snapshot(self.root / 'out')
        (self.root / 'bad.ttf').write_bytes(b'corrupt-font')
        (self.root / 'bad.png').write_bytes(b'corrupt-image')
        cases = [
            document(css='@font-face{font-family:Broken;src:url(missing.ttf)}#poster{font-family:Broken}'),
            document(css='@font-face{font-family:Broken;src:url(bad.ttf)}#poster{font-family:Broken}'),
            document('<img src="bad.png">'),
            document('<img loading="lazy" src="missing.png" style="margin-top:1800px">'),
            document(css='section{background-image:url(missing-bg.png)}'),
        ]
        for content in cases:
            with self.subTest(content=content):
                html.write_text(content, encoding='utf-8')
                result = self.cli(html)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('RESOURCE', result.stderr)
                self.assertEqual(snapshot(self.root / 'out'), before)

    def test_unused_font_does_not_fail_and_lazy_image_decodes(self):
        Image.new('RGB', (20, 20), 'red').save(self.root / 'image.png')
        html = self.html(document('<img loading="lazy" src="image.png" style="margin-top:1800px">',
                                  '@font-face{font-family:Unused;src:url(missing-unused.ttf)}'))
        result = self.cli(html)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_filename_fragment_and_query_are_encoded(self):
        name = 'chapter#one %中文.html' if os.name == 'nt' else 'chapter#one ?%.html'
        result = self.cli(self.html(name=name))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / 'out' / (Path(name).stem + '.png')).exists())

    def test_missing_input_and_invalid_scale_exit_two(self):
        for script in ('poster.py', 'render_png.py'):
            with self.subTest(script=script):
                self.assertEqual(self.cli(self.root / 'missing.html', script=script).returncode, 2)
                self.assertEqual(self.cli(self.html(), '--scale', 'nan', script=script).returncode, 2)

    def test_content_blocker_exits_one_and_publishes_diagnostics(self):
        result = self.cli(self.html(document('<p style="width:300px;overflow:hidden;white-space:nowrap">这是会超出容器而被裁切的一行长文字</p>')))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('T-OVERFLOW', result.stdout)
        self.assertTrue((self.root / 'out/book-audit.json').exists())

    def test_http_failure_is_render_failure_not_error_page(self):
        html = self.html()
        server = render_png.serve(self.root / 'nonexistent')
        with patch.object(render_png, 'serve', return_value=server):
            with self.assertRaisesRegex(Exception, 'HTTP.*404'):
                self.render(html)
        self.assertFalse((self.root / 'out/book.png').exists())

    def test_derived_image_failure_preserves_every_previous_artifact(self):
        import poster
        html = self.html()
        self.assertEqual(self.cli(html).returncode, 0)
        before = snapshot(self.root / 'out')
        html.write_text(document('新版正文'), encoding='utf-8')
        with patch.object(sys, 'argv', ['poster.py', str(html), '--outdir', str(self.root / 'out'), '--scale', '1']), \
             patch.object(poster, 'overview', side_effect=OSError('injected disk failure')), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                poster.main()
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(snapshot(self.root / 'out'), before)


class PublicationTests(TempTests):
    @unittest.skipIf(os.name == 'nt', 'POSIX generation-pointer contract; Windows covered by portable publication tests')
    def test_commit_switches_all_aliases_once_and_keeps_unrelated_files(self):
        source = self.html()
        png, audit = self.root / 'book.png', self.root / 'audit.json'
        unrelated = self.root / 'my-notes.txt'
        unrelated.write_text('keep me', encoding='utf-8')
        paths = [png, audit]
        with render_png.OutputTransaction(paths, source) as tx:
            tx.path(png).write_text('old image', encoding='utf-8')
            tx.path(audit).write_text('old audit', encoding='utf-8')
            tx.commit()
        old_target = png.resolve()
        real_replace = os.replace
        def replace(src, dst):
            if Path(dst).name == 'current':
                self.assertEqual(png.read_text(encoding='utf-8'), 'old image')
                self.assertEqual(audit.read_text(encoding='utf-8'), 'old audit')
            return real_replace(src, dst)
        with render_png.OutputTransaction(paths, source) as tx, patch.object(render_png.os, 'replace', side_effect=replace):
            tx.path(png).write_text('new image', encoding='utf-8')
            tx.path(audit).write_text('new audit', encoding='utf-8')
            tx.commit()
        self.assertNotEqual(old_target, png.resolve())
        self.assertEqual(png.read_text(encoding='utf-8'), 'new image')
        self.assertEqual(audit.read_text(encoding='utf-8'), 'new audit')
        self.assertEqual(unrelated.read_text(encoding='utf-8'), 'keep me')

    @unittest.skipIf(os.name == 'nt', 'POSIX pointer rollback; Windows covered by portable rollback tests')
    def test_failed_commit_restores_legacy_files_and_directory(self):
        source = self.html()
        png, sections = self.root / 'book.png', self.root / 'sections'
        Image.new('RGB', (10, 10), 'red').save(png)
        old_main = png.read_bytes()
        sections.mkdir()
        Image.new('RGB', (10, 10), 'blue').save(sections / 'old.png')
        old_section = (sections / 'old.png').read_bytes()
        (sections / '_sections.json').write_text('[{"name":"old"}]', encoding='utf-8')
        real_replace = os.replace
        def replace(src, dst):
            if Path(dst).name == 'current':
                raise OSError('injected publication failure')
            return real_replace(src, dst)
        with self.assertRaisesRegex(OSError, 'injected'), render_png.OutputTransaction([png, sections], source) as tx:
            tx.path(png).write_bytes(b'new-main')
            tx.path(sections).mkdir()
            (tx.path(sections) / 'new.png').write_bytes(b'new-section')
            with patch.object(render_png.os, 'replace', side_effect=replace):
                tx.commit()
        self.assertFalse(png.is_symlink())
        self.assertFalse(sections.is_symlink())
        self.assertEqual(png.read_bytes(), old_main)
        self.assertEqual((sections / 'old.png').read_bytes(), old_section)

    def test_input_conflicts_rejected_before_write(self):
        source = self.html()
        original = source.read_bytes()
        for paths in ([source], [self.root], [self.root / 'book.png', self.root / 'book.png']):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                with render_png.OutputTransaction(paths, source):
                    self.fail('must reject conflict')
        hardlink = self.root / 'input-alias.png'
        os.link(source, hardlink)
        with self.assertRaises(ValueError):
            render_png.OutputTransaction([hardlink], source)
        self.assertEqual(source.read_bytes(), original)

    @unittest.skipIf(os.name == 'nt', 'POSIX symlinks; portable unknown files/reparse checks tested separately')
    def test_unknown_files_and_external_symlinks_are_not_overwritten(self):
        source = self.html()
        target = self.root / 'book.png'
        target.write_text('private notes, not an output', encoding='utf-8')
        with self.assertRaises(ValueError):
            with render_png.OutputTransaction([target], source):
                self.fail('unknown file must be refused')
        self.assertEqual(target.read_text(encoding='utf-8'), 'private notes, not an output')
        target.unlink()
        victim = self.root / 'private.txt'
        victim.write_text('untouched', encoding='utf-8')
        target.symlink_to(victim)
        with self.assertRaises(ValueError):
            with render_png.OutputTransaction([target], source):
                self.fail('unknown symlink must be refused')
        self.assertEqual(victim.read_text(encoding='utf-8'), 'untouched')
        target.unlink()
        target.symlink_to(source)
        with self.assertRaises(ValueError):
            render_png.OutputTransaction([target], source)

    @unittest.skipIf(os.name == 'nt', 'POSIX generation-pointer contract')
    def test_tampered_current_pointer_and_storage_symlink_rejected(self):
        source = self.html()
        target = self.root / 'book.png'
        tx = render_png.OutputTransaction([target], source)
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'private.txt').write_text('keep', encoding='utf-8')
        tx.root.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            with tx:
                self.fail('storage symlink must be refused')
        tx.root.unlink()
        with render_png.OutputTransaction([target], source) as tx:
            tx.path(target).write_text('old', encoding='utf-8')
            tx.commit()
        current = tx.root / 'current'
        current.unlink()
        current.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            with render_png.OutputTransaction([target], source):
                self.fail('escaped current must be refused')
        self.assertEqual((outside / 'private.txt').read_text(encoding='utf-8'), 'keep')

    @unittest.skipIf(os.name == 'nt', 'POSIX generation-pointer contract')
    def test_preexisting_pointer_names_are_preserved_on_failure(self):
        source = self.html()
        for kind in ('file', 'directory'):
            with self.subTest(kind=kind):
                target = self.root / (kind + '.png')
                Image.new('RGB', (10, 10), 'red').save(target)
                original = target.read_bytes()
                transaction = render_png.OutputTransaction([target], source)
                # Establish owned storage without publishing, like a failed build.
                with transaction:
                    pass
                unknown = transaction.root / 'next'
                if kind == 'file':
                    unknown.write_text('unrelated user content', encoding='utf-8')
                else:
                    unknown.mkdir()
                    (unknown / 'private.txt').write_text('unrelated user content', encoding='utf-8')
                real_replace = os.replace
                def replace(src, dst):
                    if Path(dst).name == 'current':
                        raise OSError('injected switch failure')
                    return real_replace(src, dst)
                with self.assertRaises(OSError), render_png.OutputTransaction([target], source) as tx:
                    tx.path(target).write_bytes(b'new')
                    with patch.object(render_png.os, 'replace', side_effect=replace):
                        tx.commit()
                self.assertFalse(target.is_symlink())
                self.assertEqual(target.read_bytes(), original)
                content = unknown if kind == 'file' else unknown / 'private.txt'
                self.assertEqual(content.read_text(encoding='utf-8'), 'unrelated user content')

    @unittest.skipIf(os.name == 'nt', 'POSIX generation paths; portable owned-storage paths checked separately')
    def test_output_inside_published_directory_or_generation_rejected(self):
        source = self.html()
        target, sections = self.root / 'book.png', self.root / 'sections'
        with render_png.OutputTransaction([target, sections], source) as tx:
            tx.path(target).write_text('old image', encoding='utf-8')
            tx.path(sections).mkdir()
            (tx.path(sections) / 'old.png').write_text('old section', encoding='utf-8')
            tx.commit()
        for audit in (sections / 'new-audit.json', sections.resolve() / 'new-audit.json'):
            with self.subTest(path=audit), self.assertRaises(ValueError):
                with render_png.OutputTransaction([target, audit], source):
                    self.fail('output in managed generation must be rejected')
        self.assertEqual(target.read_text(encoding='utf-8'), 'old image')
        self.assertEqual((sections / 'old.png').read_text(encoding='utf-8'), 'old section')

    @unittest.skipIf(os.name == 'nt', 'POSIX aliases; portable optional-file preservation tested separately')
    def test_optional_output_changes_keep_cli_aliases_valid(self):
        source = self.html()
        target, audit = self.root / 'book.png', self.root / 'audit.json'
        for paths in ([target], [target, audit], [target]):
            with render_png.OutputTransaction(paths, source) as tx:
                for path in paths:
                    tx.path(path).write_text('value-' + path.name, encoding='utf-8')
                tx.commit()
        self.assertEqual(target.read_text(encoding='utf-8'), 'value-book.png')
        self.assertEqual(audit.read_text(encoding='utf-8'), 'value-audit.json')

    def test_parallel_writer_rejected(self):
        source = self.html()
        target = self.root / 'book.png'
        with render_png.OutputTransaction([target], source):
            with self.assertRaises(BlockingIOError):
                with render_png.OutputTransaction([target], source):
                    self.fail('must reject concurrent publisher')


class WindowsCompatibilityTests(TempTests):
    def test_v33_browser_discovery_preserves_explicit_and_pinned_priority(self):
        explicit = self.root / '自定义 chrome.exe'
        explicit.write_bytes(b'fixture')
        env = {'CHROMIUM_PATH': str(explicit), 'PLAYWRIGHT_BROWSERS_PATH': 'pinned'}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(render_png.find_chromium(), str(explicit))
            explicit.unlink()
            with self.assertRaises(ValueError):
                render_png.find_chromium()
        with patch.dict(os.environ, {'PLAYWRIGHT_BROWSERS_PATH': 'pinned'}, clear=True):
            self.assertIsNone(render_png.find_chromium())
        env = {'ProgramFiles': str(self.root / 'apps'), 'ProgramFiles(x86)': str(self.root / 'x86'),
               'LOCALAPPDATA': str(self.root / '用户')}
        with patch.dict(os.environ, env, clear=True):
            candidates = render_png.windows_chromium_candidates()
            self.assertIn(str(self.root / 'x86/Microsoft/Edge/Application/msedge.exe'), candidates)
            self.assertIn(str(self.root / '用户/Google/Chrome/Application/chrome.exe'), candidates)
            desired = candidates[-1]
            with patch.object(Path, 'is_file', lambda path: str(path) == desired), \
                 patch.object(render_png, 'IS_WINDOWS', True):
                self.assertEqual(render_png.find_chromium(), desired)

    def test_v33_utf8_stream_configuration_and_stringio(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding='ascii')
        try:
            render_png.configure_stdio(stream)
            stream.write('中文书名𠮷')
            stream.flush()
            self.assertEqual(raw.getvalue().decode('utf-8'), '中文书名𠮷')
            render_png.configure_stdio(io.StringIO())
        finally:
            stream.close()

    def test_v33_windows_regular_file_publication_and_rollback(self):
        source = self.html()
        png, audit, sections = self.root / 'book.png', self.root / 'audit.json', self.root / 'sections'
        Image.new('RGB', (10, 10), 'red').save(png)
        audit.write_text('{"page":{},"sections":[],"counts":{}}', encoding='utf-8')
        sections.mkdir()
        (sections / '_sections.json').write_text('[{"name":"old"}]', encoding='utf-8')
        Image.new('RGB', (10, 10), 'blue').save(sections / 'old.png')
        originals = {p: snapshot(p) if p.is_dir() else p.read_bytes() for p in (png, audit, sections)}
        real_replace = os.replace
        for fail_at in range(1, 7):
            calls = 0
            def replace(src, dst):
                nonlocal calls
                calls += 1
                if calls == fail_at:
                    raise OSError('injected regular publication failure')
                return real_replace(src, dst)
            with self.subTest(fail_at=fail_at), \
                 self.assertRaisesRegex(OSError, 'injected'), \
                 render_png.OutputTransaction([png, audit, sections], source, portable=True) as tx:
                Image.new('RGB', (10, 10), 'green').save(tx.path(png))
                tx.path(audit).write_text(audit.read_text(encoding='utf-8'), encoding='utf-8')
                tx.path(sections).mkdir()
                (tx.path(sections) / '_sections.json').write_text('[]', encoding='utf-8')
                with patch.object(render_png.os, 'replace', side_effect=replace):
                    tx.commit()
            for p, before in originals.items():
                self.assertEqual(snapshot(p) if p.is_dir() else p.read_bytes(), before)
        with render_png.OutputTransaction([png, audit, sections], source, portable=True) as tx:
            Image.new('RGB', (10, 10), 'green').save(tx.path(png))
            tx.path(audit).write_text(audit.read_text(encoding='utf-8'), encoding='utf-8')
            tx.path(sections).mkdir()
            (tx.path(sections) / '_sections.json').write_text('[]', encoding='utf-8')
            tx.commit()
        self.assertTrue(all(not p.is_symlink() for p in (png, audit, sections)))
        self.assertFalse((sections / 'old.png').exists())
        with Image.open(png) as image:
            self.assertEqual(image.getpixel((0, 0)), (0, 128, 0))

    def test_v33_portable_writer_lock_and_unknown_outputs(self):
        source = self.html()
        output = self.root / 'book.png'
        with render_png.OutputTransaction([output], source, portable=True):
            with self.assertRaises(BlockingIOError):
                with render_png.OutputTransaction([output], source, portable=True):
                    self.fail('second writer must fail')
        output.write_text('private notes', encoding='utf-8')
        with self.assertRaises(ValueError):
            with render_png.OutputTransaction([output], source, portable=True):
                self.fail('unknown file must fail')
        self.assertEqual(output.read_text(encoding='utf-8'), 'private notes')

    def test_portable_rejects_win32_trailing_dot_or_space_aliases(self):
        source = self.html()
        output = self.root / 'out.png'
        for alias in (self.root / 'out.png.', self.root / 'out.png ',
                      self.root / 'folder.' / 'audit.json', self.root / 'folder ' / 'audit.json'):
            with self.subTest(alias=str(alias)), self.assertRaisesRegex(ValueError, 'trailing'):
                render_png.OutputTransaction([output, alias], source, portable=True)
        for path in (PureWindowsPath('C:/out.png'), PureWindowsPath('//server/share/out.png')):
            render_png.validate_portable_components(path)  # drive/UNC anchors are not filenames
        for path in (PureWindowsPath('C:/out.png.'), PureWindowsPath('//server/share/folder /out.png')):
            with self.subTest(path=str(path)), self.assertRaisesRegex(ValueError, 'trailing'):
                render_png.validate_portable_components(path)
        self.assertFalse(output.exists())

    def test_portable_missing_drive_or_unc_root_fails_bounded(self):
        source = self.html()
        for pure in (PureWindowsPath('Z:/offline/audit.json'), PureWindowsPath('//offline/share/out/audit.json')):
            probes = []
            class MissingPath:
                def __init__(self, path):
                    self.path = path
                @property
                def parent(self):
                    return MissingPath(self.path.parent)
                def exists(self):
                    probes.append(self.path)
                    if len(probes) > 8:
                        raise AssertionError('ancestor search did not stop at nonexistent root')
                    return False
                def __eq__(self, other):
                    return isinstance(other, MissingPath) and self.path == other.path
                def __str__(self):
                    return str(self.path)
            target = MissingPath(pure)
            tx = render_png.OutputTransaction([self.root / 'book.png'], source, portable=True)
            tx.root.mkdir()
            tx.paths = [target]
            with self.subTest(path=str(pure)), patch.object(render_png, 'IS_WINDOWS', False), \
                 patch.object(render_png, 'is_redirect', return_value=False), \
                 self.assertRaisesRegex(ValueError, 'ancestor|root|volume'):
                tx.enter_portable()
            self.assertLessEqual(len(probes), 8)
            tx.root.rmdir()

    def test_portable_unlisted_section_png_is_not_deleted(self):
        source = self.html()
        output, sections = self.root / 'book.png', self.root / 'sections'
        Image.new('RGB', (10, 10), 'red').save(output)
        sections.mkdir()
        for name in ('old.png', 'untracked-user.png'):
            Image.new('RGB', (10, 10), 'blue').save(sections / name)
        for manifest in ([{'name': 'old'}], [{'name': 'old', 'file': 'old.png'}]):
            (sections / '_sections.json').write_text(json.dumps(manifest), encoding='utf-8')
            before = snapshot(sections)
            with self.subTest(manifest=manifest), self.assertRaisesRegex(ValueError, 'unlisted|manifest'):
                with render_png.OutputTransaction([output, sections], source, portable=True) as tx:
                    Image.new('RGB', (10, 10), 'green').save(tx.path(output))
                    tx.path(sections).mkdir()
                    (tx.path(sections) / '_sections.json').write_text('[]', encoding='utf-8')
                    tx.commit()
            self.assertEqual(snapshot(sections), before)

    def test_portable_alias_identity_shares_lock_and_staged_name(self):
        source = self.html()
        output, alias = self.root / 'Poster.png', self.root / 'poster.PNG'
        with render_png.OutputTransaction([output], source, portable=True) as first:
            with self.assertRaises(BlockingIOError):
                with render_png.OutputTransaction([alias], source, portable=True):
                    self.fail('case alias must share the publication lock')
            self.assertEqual(first.path(output), first.path(alias))
        with self.assertRaisesRegex(ValueError, 'distinct'):
            render_png.OutputTransaction([output, alias], source, portable=True)
        composed = render_png.OutputTransaction([self.root / 'Café.png'], source, portable=True)
        decomposed = render_png.OutputTransaction([self.root / 'Cafe\u0301.PNG'], source, portable=True)
        self.assertEqual(composed.root, decomposed.root)
        # Existing POSIX generations must keep their historical hash and suffix.
        posix = render_png.OutputTransaction([output], source, portable=False)
        expected = hashlib.sha256(str(render_png.output_path(output)).encode()).hexdigest()[:16]
        self.assertEqual(posix.root.name, '.poster-' + expected)
        posix.stage = self.root
        self.assertEqual(posix.path(output).name, expected + '.png')

    def test_portable_alias_identity_cannot_bypass_recovery(self):
        source = self.html()
        output, alias = self.root / 'Poster.png', self.root / 'poster.PNG'
        Image.new('RGB', (10, 10), 'red').save(output)
        old_bytes = output.read_bytes()
        actual_replace = os.replace
        calls = 0
        def replace(src, dst):
            nonlocal calls
            calls += 1
            if calls in (2, 3):
                raise OSError('install and rollback blocked')
            return actual_replace(src, dst)
        with self.assertRaisesRegex(RuntimeError, 'rollback incomplete'), \
             render_png.OutputTransaction([output], source, portable=True) as tx:
            Image.new('RGB', (10, 10), 'blue').save(tx.path(output))
            with patch.object(render_png.os, 'replace', side_effect=replace):
                tx.commit()
        with self.assertRaisesRegex(ValueError, 'recovery'):
            with render_png.OutputTransaction([alias], source, portable=True):
                self.fail('case alias must not bypass an unrecovered backup')
        self.assertEqual(next(tx.root.glob('backup-*/*')).read_bytes(), old_bytes)

    def test_v33_portable_rollback_failure_keeps_recovery_backup(self):
        source = self.html()
        output = self.root / 'book.png'
        Image.new('RGB', (10, 10), 'red').save(output)
        previous = output.read_bytes()
        actual_replace = os.replace
        calls = 0
        def replace(src, dst):
            nonlocal calls
            calls += 1
            if calls in (2, 3):
                raise OSError('install and rollback blocked')
            return actual_replace(src, dst)
        with self.assertRaisesRegex(RuntimeError, 'rollback incomplete'), \
             render_png.OutputTransaction([output], source, portable=True) as tx:
            Image.new('RGB', (10, 10), 'blue').save(tx.path(output))
            with patch.object(render_png.os, 'replace', side_effect=replace):
                tx.commit()
        backups = list(tx.root.glob('backup-*/*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), previous)
        with self.assertRaisesRegex(ValueError, 'recovery'):
            with render_png.OutputTransaction([output], source, portable=True):
                self.fail('unrecovered backup must block a later writer')

    def test_v33_portable_preserves_optional_outputs_and_rejects_storage_paths(self):
        source = self.html()
        output, audit = self.root / 'book.png', self.root / 'audit.json'
        for targets in ([output, audit], [output]):
            with render_png.OutputTransaction(targets, source, portable=True) as tx:
                Image.new('RGB', (10, 10), 'red').save(tx.path(output))
                if audit in targets:
                    tx.path(audit).write_text('{"page":{},"sections":[],"counts":{}}', encoding='utf-8')
                tx.commit()
        self.assertTrue(audit.is_file())
        with self.assertRaisesRegex(ValueError, 'managed publication storage'):
            render_png.OutputTransaction([tx.root / 'intruder.png'], source, portable=True)
        victim = self.root / 'private.txt'
        victim.write_text('keep', encoding='utf-8')
        with patch.object(render_png, 'is_redirect', side_effect=lambda p: p.resolve() == output.resolve()):
            with self.assertRaisesRegex(ValueError, '(?i)redirected'):
                with render_png.OutputTransaction([output], source, portable=True):
                    self.fail('reparse point must be rejected')
        self.assertEqual(victim.read_text(encoding='utf-8'), 'keep')

    def test_v33_windows_lock_uses_standard_byte_lock(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        locking = Mock()
        module = SimpleNamespace(LK_NBLCK=2, locking=locking)
        with patch.dict(sys.modules, {'msvcrt': module}), patch.object(render_png, 'IS_WINDOWS', True):
            with render_png.acquire_lock(self.root / 'lock'):
                self.assertEqual(locking.call_args.args[1:], (2, 1))
            locking.side_effect = OSError('locked')
            with self.assertRaises(BlockingIOError):
                render_png.acquire_lock(self.root / 'lock')

    def test_v33_restricted_stdout_keeps_cli_exit_contract(self):
        html = self.html(document('<p style="font-size:69px">中文𠮷</p>'), name='中文𠮷.html')
        env = dict(os.environ, PYTHONIOENCODING='ascii', PYTHONUTF8='0')
        result = subprocess.run([sys.executable, str(SCRIPTS / 'poster.py'), str(html),
                                 '--outdir', str(self.root / 'out')], env=env,
                                capture_output=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('中文𠮷', result.stdout)
        self.assertIn('T-MIN-FONT', result.stdout)
        audit = json.loads((self.root / 'out/中文𠮷-audit.json').read_text(encoding='utf-8'))
        self.assertEqual(audit['fontFloorPx'], 70)
        failed = subprocess.run([sys.executable, str(SCRIPTS / 'render_png.py'),
                                 str(self.root / '不存在𠮷.html'), str(self.root / 'fail.png')],
                                env=env, capture_output=True, encoding='utf-8', timeout=60)
        self.assertEqual(failed.returncode, 2)
        self.assertIn('不存在𠮷', failed.stderr)

    def test_v33_windows_font_candidates_use_system_root(self):
        with patch.dict(os.environ, {'WINDIR': str(self.root / '系统')}, clear=True):
            self.assertIn(str(self.root / '系统/Fonts/msyh.ttc'), contact_sheet.font_candidates())


class ResourceAndSheetTests(TempTests):
    def test_contact_sheet_obeys_manifest_order_ignoring_stale_pngs(self):
        directory = self.root / 'sections'
        directory.mkdir()
        for name, color in (('01-old', 'red'), ('02-blue', 'blue'), ('03-green', 'green')):
            Image.new('RGB', (760, 100), color).save(directory / (name + '.png'))
        (directory / '_sections.json').write_text(json.dumps([{'name': '03-green'}, {'name': '02-blue'}]), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            contact_sheet.from_sections(directory, self.root / 'sheet.png')
        with Image.open(self.root / 'sheet.png') as im:
            self.assertEqual(im.height, 330)
            self.assertEqual(im.getpixel((400, 100)), (0, 128, 0))
            self.assertEqual(im.getpixel((400, 250)), (0, 0, 255))

    def test_overview_keeps_aspect_ratio(self):
        Image.new('RGB', (900, 900), 'white').save(self.root / 'main.png')
        with contextlib.redirect_stdout(io.StringIO()):
            contact_sheet.overview(self.root / 'main.png', self.root / 'overview.png', 3, 300)
        with Image.open(self.root / 'overview.png') as im:
            self.assertEqual(im.size, (972, 136))

    @unittest.skipIf(os.name == 'nt', 'fetch_fonts.sh is a POSIX-only maintenance tool; bundled-font rendering still runs')
    def test_all_six_font_caches_verify_sha_without_network(self):
        copy = self.root / 'skill'
        (copy / 'scripts').mkdir(parents=True)
        fonts = copy / 'assets/fonts'
        fonts.mkdir(parents=True)
        shutil.copy2(SCRIPTS / 'fetch_fonts.sh', copy / 'scripts/fetch_fonts.sh')
        shutil.copy2(SKILL / 'assets/LICENSE-CC0.txt', copy / 'assets/LICENSE-CC0.txt')
        for src in (SKILL / 'assets/fonts').iterdir():
            if src.suffix in ('.otf', '.ttf'):
                (fonts / src.name).symlink_to(src)
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        curl = bin_dir / 'curl'
        curl.write_text('#!/bin/sh\nprintf "network-disabled-test\\n" >&2\nexit 97\n', encoding='utf-8')
        curl.chmod(0o755)
        env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ['PATH'])
        command = ['bash', str(copy / 'scripts/fetch_fonts.sh')]
        good = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(good.returncode, 0, good.stderr)
        for path in sorted(fonts.iterdir()):
            if path.suffix not in ('.otf', '.ttf'):
                continue
            with self.subTest(font=path.name):
                path.unlink()  # removes our fixture symlink only
                path.write_bytes(b'corrupt-cache')
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn('Font library ready', result.stdout)
                path.unlink()
                path.symlink_to(SKILL / 'assets/fonts' / path.name)

    def test_idle_connection_does_not_block_requests_or_cleanup(self):
        (self.root / 'ok.html').write_text('OK', encoding='utf-8')
        server = render_png.serve(self.root)
        idle = socket.create_connection(server.server_address, timeout=1)
        idle.sendall(b'GET /ok.html HTTP/1.0\r\n')
        conn = http.client.HTTPConnection(*server.server_address, timeout=1)
        stopped = threading.Event()
        try:
            conn.request('GET', '/ok.html')
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b'OK')
        finally:
            conn.close()
            def stop():
                server.shutdown()
                server.server_close()
                stopped.set()
            thread = threading.Thread(target=stop, daemon=True)
            thread.start()
            finished = stopped.wait(1.5)
            idle.close()
            thread.join(3)
        self.assertTrue(finished, 'cleanup waits for a stalled client')


if __name__ == '__main__':
    unittest.main(verbosity=2)
