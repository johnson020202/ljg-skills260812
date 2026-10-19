import ast
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('format_builder', Path(__file__).with_name('build_format.py'))
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
REPO = Path(__file__).resolve().parents[1]


class FormatBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / 'source with spaces'
        self.source.mkdir()
        for relative, data in {
            'README.md': 'Source inventory\n',
            '.gitignore': '.cache/\n',
            '.claude-plugin/plugin.json': '{}',
            '.claude-plugin/marketplace.json': '{}',
            'scripts/check.py': 'print("check")\n',
            'scripts/setup.py': 'print("setup")\n',
            '.github/workflows/check.yml': 'name: checks\n',
            'docs/example.md': 'Documentation\n',
            'skills/ljg-example/SKILL.md': '---\nname: ljg-example\ndescription: example\n---\n',
            'skills/ljg-example/Template.org': '#+title: A: B\n#+date: [2026-10-19 Mon 12:00]\n\n* Heading\nBody\n',
            'skills/ljg-example/Tools/tool.ts': 'console.log("untouched")\n',
            'skills/fix-ljg-org-to-md/SKILL.md': '---\nname: fix-ljg-org-to-md\ndescription: Formats\n---\nUse org input or markdown output.\n',
        }.items():
            target = self.source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(data, encoding='utf-8')
        converter = self.source / 'skills/ljg-push/Tools/markdown.py'
        converter.parent.mkdir(parents=True)
        shutil.copyfile(REPO / 'skills/ljg-push/Tools/markdown.py', converter)

    def test_complete_markdown_distribution_keeps_root_and_runtime(self):
        before = BUILDER.fingerprint(BUILDER.collect(self.source))
        output = self.base / 'md output'
        manifest = BUILDER.build(self.source, output, 'md')
        self.assertEqual(before, BUILDER.fingerprint(BUILDER.collect(self.source)))
        self.assertEqual(manifest['format'], 'md')
        self.assertTrue((output / 'skills/ljg-example/Template.md').is_file())
        self.assertFalse((output / 'skills/ljg-example/Template.org').exists())
        for relative in ['scripts/check.py', 'scripts/setup.py', '.github/workflows/check.yml', 'docs/example.md',
                         'skills/ljg-example/Tools/tool.ts', 'skills/fix-ljg-org-to-md/SKILL.md']:
            self.assertEqual((self.source / relative).read_bytes(), (output / relative).read_bytes())
        self.assertEqual(manifest['outputFingerprint'], BUILDER.fingerprint(BUILDER.collect(output)))

    def test_org_copy_is_byte_identical_and_deterministic(self):
        first = BUILDER.build(self.source, self.base / 'org-a', 'org')
        second = BUILDER.build(self.source, self.base / 'org-b', 'org')
        self.assertEqual(first, second)
        self.assertEqual(first['sourceFingerprint'], first['outputFingerprint'])

    def test_existing_output_is_never_overwritten(self):
        output = self.base / 'existing'
        output.mkdir()
        (output / 'keep').write_text('user file')
        with self.assertRaisesRegex(ValueError, 'new directory'):
            BUILDER.build(self.source, output, 'md')
        self.assertEqual((output / 'keep').read_text(), 'user file')

    def test_input_symlinks_and_nonregular_files_are_rejected(self):
        link = self.source / 'skills/ljg-example/link'
        try:
            link.symlink_to(self.source / 'README.md')
        except OSError:
            self.skipTest('This platform does not allow creating symlinks')
        with self.assertRaisesRegex(ValueError, 'Non-regular'):
            BUILDER.build(self.source, self.base / 'output', 'md')
        self.assertFalse((self.base / 'output').exists())

    def test_caches_and_credentials_are_excluded(self):
        for relative in ['skills/ljg-example/node_modules/pkg/x.js', 'skills/ljg-example/.env',
                         'skills/ljg-example/__pycache__/x.pyc', '.cache/large.bin']:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('not a release input')
        manifest = BUILDER.build(self.source, self.base / 'output', 'org')
        paths = {item['path'] for item in manifest['files']}
        self.assertFalse(any('node_modules' in path or '__pycache__' in path or path.endswith('.env') for path in paths))
        self.assertNotIn('.cache/large.bin', paths)

    def test_source_subtree_cannot_be_output(self):
        with self.assertRaisesRegex(ValueError, 'distribution inputs'):
            BUILDER.build(self.source, self.source / 'skills/generated', 'md')
        self.assertFalse((self.source / 'skills/generated').exists())

    def test_conversion_failure_publishes_nothing(self):
        output = self.base / 'output'
        with patch.object(BUILDER, 'converter', return_value=lambda _: (_ for _ in ()).throw(ValueError('bad input'))):
            with self.assertRaisesRegex(ValueError, 'bad input'):
                BUILDER.build(self.source, output, 'md')
        self.assertFalse(output.exists())
        self.assertFalse(list(self.base.glob('.output-build-*')))

    def test_source_mutation_during_conversion_is_rejected(self):
        def mutate(tree):
            (self.source / 'README.md').write_text('concurrent change')
            return tree
        with patch.object(BUILDER, 'converter', return_value=mutate):
            with self.assertRaisesRegex(ValueError, 'changed during conversion'):
                BUILDER.build(self.source, self.base / 'output', 'md')
        self.assertFalse((self.base / 'output').exists())

    def test_cannot_reverse_markdown_to_org(self):
        output = self.base / 'md'
        BUILDER.build(self.source, output, 'md')
        with self.assertRaisesRegex(ValueError, 'Cannot reconstruct'):
            BUILDER.build(output, self.base / 'org', 'org')

    def test_case_alias_output_cannot_modify_source(self):
        with self.assertRaisesRegex(ValueError, 'distribution inputs'):
            BUILDER.build(self.source, self.source / 'SKILLS/generated', 'md')
        self.assertFalse((self.source / 'skills/generated').exists())

    def test_case_alias_conversion_collision_is_rejected(self):
        (self.source / 'skills/ljg-example/template.md').write_text('existing Markdown must survive')
        with self.assertRaisesRegex(ValueError, '[Cc]ollision|alias'):
            BUILDER.build(self.source, self.base / 'output', 'md')
        self.assertFalse((self.base / 'output').exists())
        self.assertEqual((self.source / 'skills/ljg-example/template.md').read_text(), 'existing Markdown must survive')

    def test_publisher_and_builder_share_root_scope(self):
        publisher = ast.parse((REPO / 'skills/ljg-push/Tools/publish.py').read_text(encoding='utf-8'))
        assignment = next(node for node in publisher.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == 'ROOT_PATHS' for target in node.targets))
        self.assertEqual(ast.literal_eval(assignment.value), BUILDER.ROOT_PATHS)

    def test_output_manifest_matches_all_files(self):
        output = self.base / 'org'
        manifest = BUILDER.build(self.source, output, 'org')
        self.assertEqual(json.loads((output / BUILDER.MANIFEST).read_text()), manifest)
        self.assertEqual(len(manifest['files']), len(BUILDER.collect(output)))


if __name__ == '__main__':
    unittest.main()
