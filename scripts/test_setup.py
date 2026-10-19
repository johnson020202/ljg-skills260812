import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('repository_setup', Path(__file__).with_name('setup.py'))
SETUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SETUP)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        module = self.root / 'skills/ljg-card'
        (module / 'node_modules/playwright').mkdir(parents=True)
        (module / 'package.json').write_text('{}')
        (module / 'node_modules/playwright/cli.js').write_text('')
        self.calls = []

    def invoke(self, args=(), version='1.3.14'):
        def record(command, cwd, env):
            self.calls.append((command, cwd, env))
        with patch.object(SETUP, 'ROOT', self.root), patch.object(SETUP, 'run', record), \
             patch.object(SETUP.shutil, 'which', return_value='/fake/bun'), \
             patch.object(SETUP.subprocess, 'check_output', return_value=version), \
             patch.object(SETUP.sys, 'argv', ['setup.py', *args]), \
             patch.dict(SETUP.os.environ, {'PLAYWRIGHT_BROWSERS_PATH': '/outside-browser-cache'}, clear=True), contextlib.redirect_stdout(io.StringIO()):
            return SETUP.main()

    def test_install_is_checkout_local_and_frozen(self):
        self.assertEqual(self.invoke(), 0)
        commands = [call[0] for call in self.calls]
        self.assertIn(['install', '--frozen-lockfile', '--ignore-scripts'], [command[1:] for command in commands])
        self.assertTrue(any(str(self.root / '.venv') in command for command in commands))
        for _, cwd, env in self.calls:
            self.assertTrue(cwd == self.root or self.root in cwd.parents)
            self.assertEqual(env['PLAYWRIGHT_BROWSERS_PATH'], str(self.root / '.cache/ms-playwright'))
            self.assertEqual(env['PLAYWRIGHT_SKIP_BROWSER_GC'], '1')
        pip = next(command for command in commands if 'pip' in command)
        self.assertTrue(pip[0].startswith(str(self.root / '.venv')))

    def test_os_packages_are_opt_in(self):
        self.invoke()
        self.assertFalse(any('--with-deps' in command for command, _, _ in self.calls))
        self.calls.clear()
        self.invoke(['--with-deps'])
        browser_calls = [command for command, _, _ in self.calls if '--only-shell' in command]
        self.assertEqual(len(browser_calls), 2)
        self.assertTrue(all('--with-deps' in command for command in browser_calls))

    def test_skip_browsers_does_not_download_them(self):
        self.invoke(['--skip-browsers'])
        self.assertFalse(any('--only-shell' in command for command, _, _ in self.calls))
        self.assertTrue(any('pip' in command for command, _, _ in self.calls))

    def test_old_bun_is_rejected_before_installs(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.invoke(version='1.2.0')
        self.assertEqual(self.calls, [])

    def test_book_poster_scope_needs_no_bun(self):
        with patch.object(SETUP, 'ROOT', self.root), patch.object(SETUP.shutil, 'which', return_value=None), \
             patch.object(SETUP, 'run') as run, patch.object(SETUP.sys, 'argv', ['setup.py', '--scope', 'book-poster']), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(SETUP.main(), 0)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(any('pip' in command for command in commands))
        self.assertEqual(sum('--only-shell' in command for command in commands), 1)
        self.assertFalse(any('--frozen-lockfile' in command for command in commands))

    def test_non_environment_directory_is_not_overwritten(self):
        (self.root / '.venv').mkdir()
        (self.root / '.venv/keep.txt').write_text('user content')
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.invoke()
        self.assertEqual(self.calls, [])
        self.assertEqual((self.root / '.venv/keep.txt').read_text(), 'user content')

    def test_symlinked_environment_is_rejected(self):
        target = self.root / 'other'
        target.mkdir()
        (self.root / '.venv').symlink_to(target, target_is_directory=True)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.invoke()
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
