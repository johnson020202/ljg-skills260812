import contextlib
import importlib.util
import io
import json
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('repository_check', Path(__file__).with_name('check.py'))
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        skill = self.root / 'skills/ljg-example'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('---\nname: ljg-example\ndescription: Example skill\n---\n')
        (self.root / 'README.md').write_text('| **ljg-example** | Example |\n')
        (self.root / '.claude-plugin').mkdir()
        self.plugin = {'version': '1.2.3', 'repository': CHECK.REPOSITORY}
        self.market = {'version': '1.2.3', 'repository': CHECK.REPOSITORY, 'plugins': [{'version': '1.2.3'}]}
        self.save_metadata()

    def save_metadata(self):
        (self.root / '.claude-plugin/plugin.json').write_text(json.dumps(self.plugin))
        (self.root / '.claude-plugin/marketplace.json').write_text(json.dumps(self.market))

    def test_complete_contract(self):
        self.assertEqual(CHECK.contract_errors(self.root), [])

    def test_missing_skill_index(self):
        (self.root / 'README.md').write_text('No inventory\n')
        self.assertTrue(any('inventory mismatch' in error for error in CHECK.contract_errors(self.root)))

    def test_version_drift(self):
        self.market['plugins'][0]['version'] = '1.2.4'
        self.save_metadata()
        self.assertTrue(any('versions must agree' in error for error in CHECK.contract_errors(self.root)))

    def test_wrong_install_identity(self):
        with (self.root / 'README.md').open('a') as stream:
            stream.write('bunx skills add lijigang/ljg-skills -g\n')
        self.assertTrue(any('upstream' in error for error in CHECK.contract_errors(self.root)))

    def test_authorship_link_is_not_installation(self):
        with (self.root / 'README.md').open('a') as stream:
            stream.write('[Original](https://github.com/lijigang/ljg-skills)\n')
        self.assertEqual(CHECK.contract_errors(self.root), [])

    def test_wrong_repository_metadata(self):
        self.plugin['repository'] = 'https://github.com/example/other'
        self.save_metadata()
        self.assertTrue(any('repository must be' in error for error in CHECK.contract_errors(self.root)))

    def test_skill_name_must_match_directory(self):
        (self.root / 'skills/ljg-example/SKILL.md').write_text('---\nname: wrong\ndescription: Example\n---\n')
        self.assertTrue(any('name must match' in error for error in CHECK.contract_errors(self.root)))

    def test_exception_does_not_leave_stale_pass_report(self):
        report = self.root / '.cache/check-results.json'
        report.parent.mkdir()
        report.write_text('{"status":"pass"}')
        with patch.object(CHECK, 'ROOT', self.root), patch.object(CHECK.sys, 'argv', ['check.py', '--static']), \
             patch.object(CHECK, 'contract_errors', side_effect=ValueError('broken metadata')):
            with self.assertRaises(ValueError):
                CHECK.main()
        self.assertEqual(json.loads(report.read_text())['status'], 'incomplete')

    def test_bun_checks_never_auto_install(self):
        (self.root / 'skills/ljg-example/example.test.ts').write_text('')
        commands = []
        def record(name, command, env, timeout, log_dir):
            commands.append(command)
            self.assertEqual(env['PLAYWRIGHT_BROWSERS_PATH'], str(self.root / '.cache/ms-playwright'))
            self.assertNotIn('CHROMIUM_PATH', env)
            return {'name': name, 'exitCode': 0}
        with patch.object(CHECK, 'ROOT', self.root), patch.object(CHECK.sys, 'argv', ['check.py']), \
             patch.object(CHECK, 'execute', side_effect=record), patch.object(CHECK.shutil, 'which', return_value='/fake/bun'), \
             patch.dict(CHECK.os.environ, {'PLAYWRIGHT_BROWSERS_PATH': '/outside', 'CHROMIUM_PATH': '/outside/chrome'}), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(CHECK.main(), 0)
        self.assertEqual(len(commands), 3)
        self.assertTrue(all('--no-install' in command for command in commands))

    def test_maintenance_skill_is_in_inventory(self):
        directory = self.root / 'skills/fix-ljg-org-to-md'
        directory.mkdir()
        (directory / 'SKILL.md').write_text('---\nname: fix-ljg-org-to-md\ndescription: Format maintenance\n---\n')
        with (self.root / 'README.md').open('a') as stream:
            stream.write('| **fix-ljg-org-to-md** | Maintenance |\n')
        self.assertEqual(CHECK.contract_errors(self.root), [])

    def test_book_poster_scope_runs_only_python_renderer(self):
        directory = self.root / 'skills/ljg-book-poster/scripts'
        directory.mkdir(parents=True)
        (directory / 'test_render.py').write_text('')
        (self.root / 'skills/ljg-example/test_other.py').write_text('')
        commands = []
        def record(name, command, env, timeout, log_dir):
            commands.append(command)
            return {'name': name, 'exitCode': 0}
        with patch.object(CHECK, 'ROOT', self.root), patch.object(CHECK.sys, 'argv', ['check.py', '--scope', 'book-poster']), \
             patch.object(CHECK, 'contract_errors', return_value=[]), patch.object(CHECK, 'execute', side_effect=record), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(CHECK.main(), 0)
        self.assertEqual(len(commands), 1)
        self.assertIn(str(directory), commands[0])
        report = json.loads((self.root / '.cache/check-results.json').read_text())
        self.assertEqual(report['scope'], 'book-poster-only')

    def test_windows_suite_name_is_a_single_filename(self):
        name = CHECK.suite_name('python', PureWindowsPath('skills/ljg-book-poster/scripts'))
        self.assertEqual(name, 'python-skills-ljg-book-poster-scripts')
        self.assertNotIn('\\', name)
        self.assertNotIn('/', name)

    def test_static_renderer_scope_does_not_claim_runtime_verification(self):
        with patch.object(CHECK, 'ROOT', self.root), patch.object(CHECK.sys, 'argv', ['check.py', '--scope', 'book-poster', '--static']), \
             patch.object(CHECK, 'execute') as execute, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(CHECK.main(), 0)
        execute.assert_not_called()
        self.assertEqual(json.loads((self.root / '.cache/check-results.json').read_text())['scope'], 'book-poster-static-only')

    def test_dependency_sources_are_not_discovered(self):
        folder = self.root / 'skills/ljg-example/node_modules/dependency'
        folder.mkdir(parents=True)
        (folder / 'external.test.ts').write_text('must not run')
        paths = CHECK.source_files(self.root)
        self.assertFalse(any('node_modules' in path.parts for path in paths))


if __name__ == '__main__':
    unittest.main()
