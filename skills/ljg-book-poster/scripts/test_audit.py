#!/usr/bin/env python3
"""Run with python3 scripts/test_audit.py; uses the renderer's browser dependencies."""
from __future__ import annotations

import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from poster import compact_report
from render_png import find_chromium

SKILL = Path(__file__).resolve().parents[1]
AUDIT = (SKILL / "scripts/audit.js").read_text()


class FontAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        launch = {"headless": True}
        chromium = find_chromium()
        if chromium:
            launch["executable_path"] = chromium
        cls.browser = cls.playwright.chromium.launch(**launch)
        cls.page = cls.browser.new_page(viewport={"width": 1440, "height": 200})

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

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

    def test_skeleton_fonts(self):
        self.page.set_content((SKILL / "assets/poster-skeleton.html").read_text())
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
