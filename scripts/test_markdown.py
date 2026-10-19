#!/usr/bin/env python3
"""Offline converter contracts: fixtures only, no user notes, installs or publish."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ljg_markdown_under_test", ROOT / "skills/ljg-push/Tools/markdown.py")
CONVERTER = importlib.util.module_from_spec(SPEC)
previous = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    SPEC.loader.exec_module(CONVERTER)
finally:
    sys.dont_write_bytecode = previous


def convert(path, text, extra=None):
    tree = {path: ("100644", text.encode()), **(extra or {})}
    return CONVERTER.mdize(tree)


def rendered(text):
    return convert("ljg-test/template.org", text)["ljg-test/template.md"][1].decode()


class MarkdownTests(unittest.TestCase):
    def test_yaml_serializes_scalars_and_tag_array(self):
        result = rendered('#+title: A: B # not a comment\n#+date: [2026-08-01 Sat 01:02]\n#+filetags: :is:test:\n#+identifier: 20260801T010203\n#+flag: false\n#+description: "quoted" \\ text\n')
        self.assertIn('title: "A: B # not a comment"', result)
        self.assertIn('date: "2026-08-01 Sat 01:02"', result)
        self.assertIn('tags: ["is", "test"]', result)
        self.assertIn('flag: "false"', result)
        self.assertEqual(result.splitlines().count('---'), 2)

    def test_org_blocks_protect_literal_content_and_quote_structure(self):
        payload = '* literal\n# literal comment\n[[file:image.png]]\n#+title: literal\n```\n'
        for kind in ('src text', 'example'):
            with self.subTest(kind=kind):
                org = '#+title: Test\n\n* Heading\n#+begin_' + kind + '\n' + payload + '#+end_' + kind.split()[0] + '\n'
                output = rendered(org)
                self.assertIn(payload, output)
                self.assertIn('````text\n', output)
                self.assertIn('# Heading', output)
        quoted = rendered('#+title: Test\n\n#+begin_quote\n*bold* testimony\n\nsecond line\n#+end_quote\n')
        self.assertIn('> **bold** testimony\n>\n> second line', quoted)

    def test_review_current_line_counterexample_and_input_are_protected(self):
        instruction = '输出必须是纯 org-mode 语法，禁止任何 markdown 语法'
        for prefix in ('反例：', '输入：', '输入示例：', '- 反例：'):
            with self.subTest(prefix=prefix):
                text = '## 格式\n' + prefix + '`' + instruction + '`\n'
                self.assertEqual(convert('ljg-test/SKILL.md', text)['ljg-test/SKILL.md'][1].decode(), text)
        active = '## 格式\n' + instruction + '\n'
        self.assertIn('输出必须是纯 Markdown 语法，不混用 Org 语法', convert('ljg-test/SKILL.md', active)['ljg-test/SKILL.md'][1].decode())

    def test_review_real_qa_four_part_output_templates(self):
        labels = ('结论', '形式化', '怎么想到的', '边界')
        for path in ('ljg-qa/Workflows/Extract.md', 'ljg-qa/References/QuestionDesign.md'):
            with self.subTest(path=path):
                text = (ROOT / 'skills' / path).read_text()
                result = convert(path, text)[path][1].decode()
                for label in labels:
                    self.assertIn('**' + label + '**：', result)
                    self.assertNotRegex(result, re.compile(r'^\*' + label + r'\*：', re.MULTILINE))
        text = '## A 的四段\n正文 *italic* 不改。\n```\n*italic* 示例而非四段输出\n```\n'
        self.assertEqual(convert('ljg-qa/SKILL.md', text)['ljg-qa/SKILL.md'][1].decode(), text)

    def test_review_indented_code_is_literal_but_adjacent_prose_converts(self):
        for indent in ('    ', '\t', '  \t', '        '):
            with self.subTest(indent=repr(indent)):
                literal = indent + 'print("输出 org-mode")\n'
                original = '# 一级\n\n' + literal
                self.assertEqual(convert('ljg-test/SKILL.md', original)['ljg-test/SKILL.md'][1].decode(), original)
                text = '输出 org-mode\n\n' + literal + '\n输出 org-mode\n'
                expected = '输出 Markdown\n\n' + literal + '\n输出 Markdown\n'
                self.assertEqual(convert('ljg-test/SKILL.md', text)['ljg-test/SKILL.md'][1].decode(), expected)
                self.assertEqual(CONVERTER.mdize(convert('ljg-test/SKILL.md', text))['ljg-test/SKILL.md'][1].decode(), expected)

    def test_review_blockquoted_fences_preserve_code(self):
        for quote in ('> ', '> > '):
            for marker in ('```', '~~~~'):
                with self.subTest(quote=quote, marker=marker):
                    text = '## 输出\n' + quote + marker + 'python\n' + quote + 'print("输出 org-mode")\n' + quote + marker + '\n'
                    self.assertEqual(convert('ljg-test/SKILL.md', text)['ljg-test/SKILL.md'][1].decode(), text)

    def test_review_org_quote_nested_code_is_literal(self):
        for block in ('src text', 'example'):
            with self.subTest(block=block):
                kind = block.split()[0]
                text = '#+begin_quote\n#+begin_' + block + '\n输出 org-mode\n#+end_' + kind + '\n#+end_quote\n'
                result = rendered(text)
                self.assertIn('> ```text\n> 输出 org-mode\n> ```', result)

    def test_review_org_quote_ignores_literal_quote_terminator_inside_code(self):
        for block in ('src text', 'example'):
            with self.subTest(block=block):
                kind = block.split()[0]
                text = '#+begin_quote\n#+begin_' + block + '\n#+end_quote\n输出 org-mode\n#+end_' + kind + '\n#+end_quote\n'
                result = rendered(text)
                self.assertIn('> ```text\n> #+end_quote\n> 输出 org-mode\n> ```', result)

    def test_generated_shell_and_org_code_remain_literal(self):
        for language, payload in [('bash', 'bun validate_note.ts /tmp/note.org\n'),
                                  ('org', '#+title: example\n* example\n'),
                                  ('text', 'User: example\n输出 org-mode\n')]:
            with self.subTest(language=language):
                output = rendered('* 输出模板\n#+begin_src ' + language + '\n' + payload + '#+end_src\n')
                self.assertIn(payload, output)

    def test_nested_output_fences_use_safe_outer_delimiter(self):
        document = '## 输出模板\n```org\n#+title: Demo\n\n#+begin_example\n* literal\n#+end_example\n```\n'
        output = convert('ljg-test/SKILL.md', document)['ljg-test/SKILL.md'][1].decode()
        self.assertIn('````markdown\n', output)
        self.assertIn('```text\n* literal\n```', output)
        self.assertEqual(CONVERTER.mdize(convert('ljg-test/SKILL.md', document))['ljg-test/SKILL.md'][1].decode(), output)

    def test_unknown_active_output_contract_refuses(self):
        with self.assertRaises(ValueError):
            convert('ljg-test/SKILL.md', '## 输出\n保存为一种未支持的 Org 文件。\n')

    def test_org_inline_format_and_links(self):
        result = rendered('* Heading\n*bold* /italic/ ~code~ =literal= [[https://example.org/a][label]] [[file:image.png]]\n')
        self.assertIn('**bold** *italic* `code` `literal` [label](https://example.org/a) ![](image.png)', result)

    def test_inline_urls_code_and_link_labels_never_leak_placeholders(self):
        for url in ('https://example.org/~user~/doc', 'https://example.org/a=b=c',
                    'https://example.org/*literal*/x', 'https://example.org/a/b/c'):
            with self.subTest(url=url):
                linked = rendered('[[' + url + '][*bold* /italic/ ~code~]]\n')
                self.assertEqual(linked, '[**bold** *italic* `code`](' + url + ')\n')
                self.assertEqual(rendered(url + '\n'), url + '\n')
                self.assertEqual(rendered('[[' + url + ']]\n'), '<' + url + '>\n')
                self.assertNotIn('\x00', linked)
        self.assertEqual(rendered('`~literal~ =code= *bold*`\n'), '`~literal~ =code= *bold*`\n')
        self.assertEqual(rendered('~[[https://example.org][link]]~\n'), '`[[https://example.org][link]]`\n')
        self.assertEqual(rendered('[[file:~user~/a=b=c.png]]\n'), '![](~user~/a=b=c.png)\n')

    def test_inline_separators_are_not_emphasis(self):
        content = '可 / 止 / 深入此节 / 引入新人物\n3 * 4 * 5\n*bold word* /italic word/\n'
        result = rendered(content)
        self.assertIn('可 / 止 / 深入此节 / 引入新人物', result)
        self.assertIn('3 * 4 * 5', result)
        self.assertIn('**bold word** *italic word*', result)

    def test_roundtable_reference_body_is_preserved(self):
        reference = ROOT / 'skills/ljg-roundtable/references/original-prompt.org'
        if reference.exists():
            source = reference.read_text()
            self.assertEqual(rendered(source).split('\n\n', 1)[1], source.split('\n\n', 1)[1])
        else:
            reference = reference.with_suffix('.md')
            source = reference.read_text()
            self.assertIn('可 / 止 / 深入此节 / 引入新人物', source)
            path = 'ljg-roundtable/references/original-prompt.md'
            self.assertEqual(convert(path, source)[path][1].decode(), source)

    def test_unclosed_and_unsupported_org_blocks_refuse(self):
        for source in ('#+begin_src text\nliteral\n', '#+begin_example\nliteral\n', '#+begin_quote\ntext\n', '#+begin_export html\n<div/>\n#+end_export\n'):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    rendered(source)

    def test_markdown_code_and_org_input_examples_are_unchanged(self):
        document = '''# Input fixtures
```ts
const fixture = `#+title: org-mode
#+date: [2026-08-01 Sat 01:02]
#+filetags: :is:
* Heading
- *label*：literal`;
```
## Org input example
```org
#+title: Input
#+date: [2026-08-01 Sat 01:02]
* Heading
```
说明：org-mode 输入保持原样；网址 https://example.org。
正文 *italic* 不改。
'''
        self.assertEqual(convert('ljg-test/Tools/Fixture.help.md', document)['ljg-test/Tools/Fixture.help.md'][1].decode(), document)

    def test_output_templates_convert_as_whole_blocks(self):
        for opener in ('```org', '```', '   ```org', '~~~org'):
            indent = '   ' if opener.startswith(' ') else ''
            fence = '~~~' if opener.startswith('~') else '```'
            text = '## 输出文件结构\n\n' + opener + '\n' + ''.join(indent + line + '\n' for line in ['#+title: 本质：Taxi', '#+date: [2026-08-01 Sat 01:02]', '#+filetags: :is:', '* Heading', '- *标签*：内容']) + indent + fence + '\n'
            with self.subTest(opener=opener):
                result = convert('ljg-test/SKILL.md', text)['ljg-test/SKILL.md'][1].decode()
                self.assertIn('title: "本质：Taxi"', result)
                self.assertIn('tags: ["is"]', result)
                self.assertIn('# Heading', result)
                self.assertIn('- **标签**：内容', result)
                self.assertEqual(sum(line.strip() == '---' for line in result.splitlines()), 2)
                self.assertNotIn('#+date:', result)

    def test_runtime_changes_only_exact_resolved_file_references(self):
        source = '''const real = new URL("../Template.org", import.meta.url);
const missing = "../missing/Template.org";
const longer = "../MyTemplate.org.bak";
const suffix = "../Template.org.bak";
const fixture = `#+title: org-mode\n* Heading\n- *标签*：literal`;
const unrelated = "Template.org";
'''
        tree = convert('ljg-test/Tools/test.ts', source, {'ljg-test/Template.org': ('100644', b'* Heading\n')})
        result = tree['ljg-test/Tools/test.ts'][1].decode()
        self.assertEqual(result, source.replace('"../Template.org"', '"../Template.md"'))

    def test_markdown_reference_resolves_from_consumer_not_basename(self):
        doc = '读取 `../Template.org`。不改 `../other/Template.org`、`MyTemplate.org.bak` 或 https://example.org/Template.org。\n'
        result = convert('ljg-test/Tools/help.md', doc, {'ljg-test/Template.org': ('100644', b'* Heading\n')})
        self.assertEqual(result['ljg-test/Tools/help.md'][1].decode(), doc.replace('`../Template.org`', '`../Template.md`'))

    def test_quoted_reference_with_spaces_is_resolved_exactly(self):
        source = 'load("../templates/My Note.org"); keep("../templates/My Note.org.bak");\n'
        result = convert('ljg-test/Tools/check.ts', source, {'ljg-test/templates/My Note.org': ('100644', b'* Heading\n')})
        self.assertEqual(result['ljg-test/Tools/check.ts'][1].decode(), source.replace('My Note.org"', 'My Note.md"'))

    def test_format_neutral_maintenance_skill_is_byte_preserved(self):
        tree = {'fix-ljg-org-to-md/SKILL.md': ('100644', b'org-mode output\n```org\n#+title: source\n```\n'),
                'fix-ljg-org-to-md/example.org': ('100644', b'* input fixture\n')}
        self.assertEqual(CONVERTER.mdize(tree), tree)

    def test_purity_modes_assets_idempotence_and_collisions(self):
        tree = {'ljg-test/template.org': ('100644', b'#+title: Test\n\n* Heading\n'),
                'ljg-test/assets/example.org': ('100644', b'\x00\xff'),
                'ljg-test/tool.py': ('100755', b'fixture = "org-mode"\n')}
        original = dict(tree)
        result = CONVERTER.mdize(tree)
        self.assertEqual(tree, original)
        self.assertEqual(result['ljg-test/assets/example.org'], tree['ljg-test/assets/example.org'])
        self.assertEqual(result['ljg-test/tool.py'], tree['ljg-test/tool.py'])
        self.assertEqual(CONVERTER.mdize(result), result)
        with self.assertRaises(ValueError):
            CONVERTER.mdize({**tree, 'ljg-test/template.md': ('100644', b'manual\n')})

    def test_real_output_contracts_and_missing_suffixes(self):
        for skill in ('blind', 'learn', 'qa', 'structure', 'think', 'read', 'relationship', 'roundtable', 'invest', 'plain', 'writes', 'constraint'):
            with self.subTest(skill=skill):
                path = 'ljg-' + skill + '/SKILL.md'
                source = (ROOT / 'skills' / path).read_text()
                result = convert(path, source)[path][1].decode()
                self.assertNotRegex(result, r'(?:禁止|禁混|禁)[^\n。]*[Mm]arkdown')
                self.assertNotRegex(result, r'__(?:reading|relationship|roundtable)\.org|投资分析-[^`\n]*\.org')
                self.assertNotRegex(result, re.compile(r'^\s*#\+(?:title|date|filetags):', re.MULTILINE))
                self.assertNotRegex(result, r'(?:保存为|生成|写成|存入|写入 notes 里的) [Oo]rg (?:文件|笔记)')
                self.assertNotIn('写入 Org 文件', result)
                if skill == 'blind':
                    self.assertIn('[在微信读书网页版阅读本章](https://weread.qq.com/', result)
                if skill == 'roundtable':
                    self.assertIn('tags: ["roundtable"]', result)

    def test_real_is_workflow_template_reference_and_all_output_bullets(self):
        path = 'ljg-is/Workflows/FindEssence.md'
        template_path = ROOT / 'skills/ljg-is/Template.org'
        template_name = 'ljg-is/Template.org' if template_path.exists() else 'ljg-is/Template.md'
        if not template_path.exists():
            template_path = ROOT / 'skills/ljg-is/Template.md'
        tree = convert(path, (ROOT / 'skills' / path).read_text(), {template_name: ('100644', template_path.read_bytes())})
        result = tree[path][1].decode()
        self.assertIn('技能根目录的 `Template.md`', result)
        self.assertNotIn('```org', result)
        self.assertIn('- **结构式**：', result)
        self.assertIn('- **替换**：', result)
        self.assertIn('`schema: ljg-is-v2`', result)

    def test_preserves_nonoutput_org_mentions_and_existing_markdown_fences(self):
        text = '# 输入\n接受 Org 笔记与 Markdown；org-mode 是一种输入。\n```markdown\n# Existing\n*italic*\n```\n```python\nprint("template.org")\n```\n'
        self.assertEqual(convert('ljg-test/SKILL.md', text)['ljg-test/SKILL.md'][1].decode(), text)

    def test_legacy_minimal_format_declaration(self):
        value = convert('ljg-test/SKILL.md', 'new source in org-mode\n')['ljg-test/SKILL.md'][1]
        self.assertIn(b'markdown', value)

    def test_actual_converted_org_and_filled_template_reach_current_validators(self):
        bun = shutil.which('bun')
        self.assertIsNotNone(bun, 'Bun is required for the real cross-format validator contract')
        org_is = re.search(r'function goodNote\(\): string \{\n  return `([\s\S]*?)`;\n\}', (ROOT / 'skills/ljg-is/Tools/ValidateNote.test.ts').read_text()).group(1)
        org_book = '''#+TITLE: 拆书：《示例》
#+SUBTITLE: 某作者 | 一次判断变化
#+DESCRIPTION: 同一组结果换一种说法，选择为什么会翻转。
#+DATE: [2026-08-12 Wed 12:00]
#+FILETAGS: :book:test:
#+IDENTIFIER: 20260812T120000

* 为什么换一种说法，选择就翻了
小李先选确定方案，换一种表述后却改选冒险方案。

* 同一决定怎样重新问一遍
他现在会先检查参照条件，再决定怎样行动。
'''
        # Run unchanged from source and generated checkouts. Fill the actual
        # template header in whichever format this checkout contains; the body is
        # an independent valid fixture, never a user note.
        skill = ROOT / 'skills/ljg-is'
        org_template = skill / 'Template.org'
        md_is = rendered(org_is)
        if org_template.is_file():
            template = org_template.read_text().split('\n\n', 1)[0]
            header = template.replace('{目标}', 'Taxi').replace('{可读时间}', '2026-08-01 Sat 01:02').replace('{时间戳}', '20260801T010203')
            filled_md = rendered(header + '\n\n' + org_is.split('\n\n', 1)[1])
        else:
            template = (skill / 'Template.md').read_text()
            header = template.split('---', 2)[1].replace('{目标}', 'Taxi').replace('{可读时间}', '2026-08-01 Sat 01:02').replace('{时间戳}', '20260801T010203')
            filled_md = '---' + header + '---' + md_is.split('---', 2)[2]
        fixtures = {'orgIs': org_is, 'mdIs': md_is, 'mdTemplateIs': filled_md, 'orgBook': org_book, 'mdBook': rendered(org_book)}
        with tempfile.TemporaryDirectory(prefix='ljg-markdown-test-') as name:
            temp = Path(name)
            (temp / 'fixtures.json').write_text(json.dumps(fixtures, ensure_ascii=False))
            for source, target in [('skills/ljg-is/Tools/ValidateNote.ts', 'is.ts'), ('skills/ljg-book/scripts/validate_note.ts', 'book.ts')]:
                shutil.copyfile(ROOT / source, temp / target)
            (temp / 'check.ts').write_text('''import { validateNoteText } from './is.ts';
import { validate } from './book.ts';
const f = await Bun.file(new URL('./fixtures.json', import.meta.url)).json();
const coverage = '- 材料等级：初拆\\n- 主要材料：原书样章\\n- 能支持到：支持核心机制与边界\\n';
const a = '20260801T010203--本质-taxi__is';
const b = '20260812T120000--拆书-示例__book';
const positive = [validateNoteText(a+'.org',f.orgIs), validateNoteText(a+'.md',f.mdIs), validateNoteText(a+'.md',f.mdTemplateIs), validate(f.orgBook,b+'.org',coverage), validate(f.mdBook,b+'.md',coverage)];
const negative = [validateNoteText(a+'.md',f.orgIs), validateNoteText(a+'.org',f.mdIs), validateNoteText(a+'.md',f.mdIs.replace('20260801T010203','20260801T010204')), validate(f.mdBook.replace('20260812T120000','20260812T120001'),b+'.md',coverage)];
const metadata = Bun.YAML.parse(f.mdIs.split('---')[1]);
console.log(JSON.stringify({positive, negative, metadata}));
if (positive.some(x=>!x.ok)||negative.some(x=>x.ok)||typeof metadata.date!=='string'||!Array.isArray(metadata.tags)) process.exit(1);
''')
            home = temp / 'home'; home.mkdir()
            result = subprocess.run([bun, '--no-install', str(temp / 'check.ts')], cwd=temp, env={**os.environ, 'HOME': str(home)}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
