#!/usr/bin/env python3
"""Run with python3 scripts/test_audit.py; uses the renderer's browser dependencies."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from poster import compact_report
from render_png import find_chromium, prepare_page, serve

SKILL = Path(__file__).resolve().parents[1]
AUDIT = (SKILL / "scripts/audit.js").read_text(encoding='utf-8')


class FontAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        launch = {"headless": True}
        chromium = find_chromium()
        if chromium:
            launch["executable_path"] = chromium
        cls.browser = cls.playwright.chromium.launch(**launch)
        cls.addClassCleanup(cls.browser.close)
        cls.page = cls.browser.new_page(viewport={"width": 1440, "height": 200})
        cls.page.route('**/*', lambda route: route.abort())  # offline regression only

    def audit(self, content, css=""):
        self.page.set_content(
            '<style>*{box-sizing:border-box;margin:0} '
            'body{font:70px/1.6 sans-serif;color:#111;background:#fff} '
            '#poster{width:1440px;padding:40px} section{margin-bottom:80px} '
            f'{css}</style><main id="poster"><section>{content}</section></main>'
        )
        self.page.evaluate("document.fonts.ready")
        return self.page.evaluate(AUDIT)

    def test_computed_font_floor(self):
        cases = [
            ('<p style="font-size:70px">正文</p>', 70, 0),
            ('<p style="font-size:69px">正文</p>', 69, 1),
            ('<p style="font-size:69.99px">正文</p>', 69.99, 1),
            ('<p style="font-size:1px">正文</p>', 1, 1),
            ('<div style="font-size:69px"><p>继承字号</p></div>', 69, 1),
            ('<p style="font-size:90px"><span style="font-size:.75em">单位</span></p>', 67.5, 1),
            ('<p style="font-size:1.5rem">来源</p>', 24, 1),
            ('<p style="font-size:90px"><span style="font-size:75%">页码</span></p>', 67.5, 1),
            ('<p style="font-size:max(70px,.42em)">单位</p>', 70, 0),
        ]
        for content, minimum, small in cases:
            with self.subTest(content=content):
                audit = self.audit(content)
                self.assertAlmostEqual(audit["minFontPx"], minimum, places=2)
                self.assertEqual(audit["fontFloorPx"], 70)
                self.assertEqual(audit["underFloorPx"], small)
                issues = [i for i in audit["issues"] if i["code"] == "T-MIN-FONT"]
                self.assertEqual(len(issues), small)
                self.assertTrue(all(i["sev"] == 1 for i in issues))

    def test_hidden_and_export_content_excluded(self):
        audit = self.audit('''
            <p style="font-size:70px">可见正文</p>
            <div style="display:none"><p style="font-size:9px">隐藏</p></div>
            <div style="opacity:0"><p style="font-size:10px">透明</p></div>
            <div style="visibility:hidden"><p style="font-size:11px">隐藏</p></div>
            <div style="content-visibility:hidden"><p style="font-size:12px">隐藏</p></div>
            <div data-export-ignore><button style="font-size:13px">导出</button></div>
        ''')
        self.assertEqual(audit["textNodes"], 1)
        self.assertEqual(audit["minFontPx"], 70)
        self.assertEqual(audit["underFloorPx"], 0)

    def test_visible_child_of_hidden_parent_is_checked(self):
        audit = self.audit('''
            <div style="visibility:hidden">
              <span style="visibility:visible;font-size:69px">可见</span>
            </div>
        ''')
        self.assertEqual(audit["underFloorPx"], 1)

    def test_generated_labels_and_counters(self):
        for pseudo in ("::before", "::after"):
            with self.subTest(pseudo=pseudo):
                audit = self.audit(
                    '<p class="label">正文</p>',
                    f'.label{pseudo}{{content:"标签";font-size:69px}}',
                )
                self.assertEqual(audit["generatedTextNodes"], 1)
                self.assertEqual(audit["underFloorPx"], 1)
                issue = next(i for i in audit["issues"] if i["code"] == "T-MIN-FONT")
                self.assertEqual(issue["pseudo"], pseudo)
        audit = self.audit(
            '<ol><li>正文</li></ol>',
            'ol{list-style:none;counter-reset:item} li{counter-increment:item} '
            'li::before{content:counter(item);font-size:70px}',
        )
        self.assertEqual(audit["generatedTextNodes"], 1)
        self.assertEqual(audit["underFloorPx"], 0)
        self.assertEqual(audit["minFontPx"], 70)

    def test_empty_poster(self):
        audit = self.audit("")
        self.assertIsNone(audit["minFontPx"])
        self.assertEqual(audit["underFloorPx"], 0)
        report, _ = compact_report(audit)
        self.assertIn("minFont=n/a", report)

    def test_report_marks_single_small_source_as_blocking(self):
        audit = self.audit('<p style="font-size:69px">来源与页码</p>')
        report, blocking = compact_report(audit)
        self.assertEqual(blocking, 1)
        self.assertIn("minFont=69px", report)
        self.assertIn("under70px=1", report)
        self.assertIn("T-MIN-FONT", report)

    def test_clipped_ranges_inside_ancestors(self):
        for css in ('width:300px;overflow:hidden;white-space:nowrap',
                    'height:30px;overflow:hidden', 'width:300px;overflow:clip;white-space:nowrap'):
            with self.subTest(css=css):
                audit = self.audit(f'<div style="{css}"><p>这是会被容器裁掉的长文字</p></div>')
                self.assertTrue(any(i['code'] == 'T-OVERFLOW' and i['sev'] == 1 for i in audit['issues']))
        audit = self.audit('<p style="width:700px">正常可见文字</p>')
        self.assertFalse(any(i['code'] == 'T-OVERFLOW' for i in audit['issues']))

    def test_widows_across_inline_nodes_and_whitespace(self):
        for text in ('一二三四', '一二三<strong>四</strong>', '一二三四   \n',
                     '<span>一二</span>三<em>四</em>   '):
            with self.subTest(text=text):
                audit = self.audit(f'<p style="width:210px;word-break:break-all;font:70px/1.4 monospace">{text}</p>')
                self.assertTrue(any(i['code'] == 'T-WIDOW' for i in audit['issues']))
        audit = self.audit('<h1 style="width:360px;word-break:break-all;font:120px/1.4 monospace">一二三四</h1>')
        self.assertTrue(any(i['code'] == 'T-WIDOW' for i in audit['issues']))
        audit = self.audit('<p style="width:210px;font:70px/1.4 monospace">一二<span>三</span><span>四五六</span></p>')
        self.assertFalse(any(i['code'] == 'T-WIDOW' for i in audit['issues']))

    def test_marker_and_transformed_font_floor(self):
        audit = self.audit('<ol style="padding-left:100px"><li>正文</li></ol>', 'li::marker{font-size:10px}')
        self.assertTrue(any(i['code'] == 'T-MIN-FONT' and i.get('pseudo') == '::marker' for i in audit['issues']))
        for css in ('transform:scale(.2)', 'scale:.2', 'zoom:.2', 'transform:scaleX(.2)'):
            with self.subTest(css=css):
                audit = self.audit(f'<div style="{css}"><p>缩小文字</p></div>')
                self.assertAlmostEqual(audit['minFontPx'], 14, places=2)
                self.assertGreater(audit['underFloorPx'], 0)
        audit = self.audit('<p style="transform:rotate(10deg)">旋转不缩小</p>')
        self.assertEqual(audit['underFloorPx'], 0)

    def test_skeleton_loads_six_visible_font_roles_offline(self):
        with tempfile.TemporaryDirectory(prefix='poster-template-') as tmp:
            root = Path(tmp)
            (root / 'book.html').write_text((SKILL / 'assets/poster-skeleton.html').read_text(encoding='utf-8'), encoding='utf-8')
            shutil.copytree(SKILL / 'assets/fonts', root / 'fonts')
            server = serve(root)
            page = self.browser.new_page(viewport={'width': 1440, 'height': 1200})
            try:
                prepare_page(page, f'http://127.0.0.1:{server.server_address[1]}/book.html')
                families = page.evaluate('''() => [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family)''')
                self.assertEqual(len(set(families)), 6)
                roles = page.evaluate('''() => ['.main','.sec-title','.book-title','.kicker','.k','.ending'].map(s => getComputedStyle(document.querySelector(s)).fontFamily.split(',')[0])''')
                self.assertEqual(len(set(roles)), 6)
                self.assertNotIn('。', page.locator('#poster').inner_text())
                audit = page.evaluate(AUDIT)
                self.assertEqual(audit['counts']['1'], 0, audit['issues'])
                self.assertEqual(audit['underFloorPx'], 0)
            finally:
                page.close()
                server.shutdown()
                server.server_close()

    def test_v33_chapter_number_duplicates_are_local_to_heading(self):
        audit = self.audit('<div class="sec-head"><b class="sec-num">01</b><h2>第1章</h2></div>')
        self.assertTrue(any(i['code'] == 'T-CHAPTER-DUP' for i in audit['issues']))
        split = self.audit('<div data-chapter-heading><b data-chapter-number>01</b><h2>第<span>一</span>章 主题</h2></div>')
        self.assertTrue(any(i['code'] == 'T-CHAPTER-DUP' for i in split['issues']))
        generated = self.audit('<div class="sec-head"><b class="sec-num"></b><h2>第1章</h2></div>',
                               '.sec-num::before{content:"01"}')
        self.assertTrue(any(i['code'] == 'T-CHAPTER-DUP' for i in generated['issues']))
        for text in ('<div class="sec-head"><b class="sec-num">01</b><h2>SWARM MIND</h2></div>',
                     '<div class="sec-head"><h2>01 章</h2></div>',
                     '<div class="chapter-map">第1章</div><div class="sec-head"><b class="sec-num">01</b><h2>主题</h2></div>',
                     '<div class="sec-head"><b class="sec-num">01</b><h2>主题</h2><span hidden>第1章</span></div>'):
            with self.subTest(text=text):
                self.assertFalse(any(i['code'] == 'T-CHAPTER-DUP' for i in self.audit(text)['issues']))

    def test_v33_huiwen_scan_is_scoped_review_not_glyph_proof(self):
        audit = self.audit('<p style="font-family:\'Huiwen Mincho\'">让药继赞钟钥认讲论证铁</p>'
                           '<p style="font-family:sans-serif">让药继赞钟钥认讲论证铁</p>'
                           '<p hidden style="font-family:\'Huiwen Mincho\'">让</p>')
        review = audit['huiwenReview']
        self.assertEqual(review['status'], 'manual-review-required')
        self.assertEqual(review['riskCharacters'], '让药继赞钟钥认讲论证铁')
        self.assertEqual(len(review['candidates']), 1)
        self.assertEqual(set(review['candidates'][0]['characters']), set('让药继赞钟钥认讲论证铁'))
        safe = self.audit('<p style="font-family:sans-serif">让</p>')['huiwenReview']
        self.assertEqual(safe['candidates'], [])
        self.assertEqual(safe['status'], 'not-requested')

    def test_skeleton_fonts(self):
        self.page.set_content((SKILL / "assets/poster-skeleton.html").read_text(encoding='utf-8'))
        self.page.evaluate("document.fonts.ready")
        self.page.evaluate(
            "document.querySelectorAll('[data-export-ignore]').forEach(el => el.style.display='none')"
        )
        audit = self.page.evaluate(AUDIT)
        self.assertEqual(audit["minFontPx"], 70)
        self.assertEqual(audit["underFloorPx"], 0)
        self.assertGreater(audit["generatedTextNodes"], 0)
        self.assertEqual(audit["counts"]["1"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
