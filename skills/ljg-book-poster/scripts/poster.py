#!/usr/bin/env python3
"""One command: render + audit + section crops + contact sheet + thumbnail.

    python3 poster.py book.html --outdir out/

Prints a compact, model-readable report on stdout: no JSON parsing, no second
Read of the PNG, no manual cropping. Everything QA needs is in this output plus
the single contact sheet image.

Exit codes: 0 = no blocking issues, 1 = P1 (must fix), 2 = render failed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image  # noqa: E402

import render_png  # noqa: E402
from contact_sheet import from_sections, overview  # noqa: E402

CODE_HINT = {
    "T-OVERFLOW": "文字超出画布：检查 width/max-width、white-space、长英文串",
    "T-UNIT-WRAP": "数字与单位被拆行：给数字+单位包一层 white-space:nowrap",
    "T-KEY-BREAK": "强调词折行：display:inline-block + 前后留白，或缩短词",
    "T-GIANT": "整句被放大：只保留 1 个最关键的词放大",
    "T-WIDOW": "末行孤字：微调 max-width 或改写该句",
    "BOTTOM-VOID": "底部大空白：检查主容器是否写死高度",
    "H-OVERFLOW": "横向溢出：检查固定宽度子元素",
    "SECTION-GAP": "区块间距过小：大章节岛之间需 64–120px",
    "EDGE-TIGHT": "圆角区块贴边：给画布左右留出 padding",
    "TOP-TIGHT": "首块贴顶：画布顶部留 32–48px",
    "C-CONTRAST": "对比度不足：提高明度差，别只靠色相区分",
    "L-FIXED": "fixed/sticky 元素在整页截图中会重复：改用 static",
    "T-MIN-FONT": "任何文字不得小于 70 CSS px：放大字号、重排或精简，含来源与图注",
}


def compact_report(audit: dict) -> tuple[str, int]:
    p = audit["page"]
    c = audit["counts"]
    lines = []
    lines.append(f"PAGE   {p['width']}x{p['height']} css (overflow={p['scrollWidth'] > p['width'] + 2})  sections={len(audit['sections'])}")
    min_font = f"{audit['minFontPx']:g}px" if audit["minFontPx"] is not None else "n/a"
    lines.append(
        f"TEXT   nodes={audit['textNodes']}  generated={audit['generatedTextNodes']}  "
        f"minFont={min_font}  under{audit['fontFloorPx']}px={audit['underFloorPx']}"
    )
    lines.append(f"ISSUES P1={c['1']} P2={c['2']} P3={c['3']}")
    review = audit.get('huiwenReview', {})
    if review.get('status') == 'manual-review-required':
        candidates = review.get('candidates', [])
        lines.append(f"GLYPHS manual-review-required (Huiwen; candidate spans={len(candidates)}; not glyph verification)")
        for candidate in candidates:
            lines.append(f"       {candidate['selector']}{candidate.get('pseudo', '')}: {candidate['characters']}")
    if audit["issues"]:
        lines.append("")
        for i in audit["issues"]:
            lines.append(
                f"  P{i['sev']} [{i['code']}] y={int(i['y'])} sec={i.get('section') or '-'} :: {i['msg']}"
            )
            hint = CODE_HINT.get(i["code"])
            if hint:
                lines.append(f"       fix: {hint}")
    else:
        lines.append("\nNo layout issues detected.")
    return "\n".join(lines), c["1"]


def main() -> None:
    render_png.configure_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("input_html", type=Path)
    ap.add_argument("--outdir", type=Path, default=Path("out"))
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--scale", type=float, default=render_png.DEFAULT_SCALE, help='output pixels per CSS px (default .75: 1080px at width 1440)')
    ap.add_argument("--thumb-width", type=int, default=440)
    args = ap.parse_args()

    html = args.input_html.resolve()
    outdir = args.outdir.absolute()
    stem = html.stem
    png = outdir / f"{stem}.png"
    slices = outdir / f"{stem}-sections"
    audit_path = outdir / f"{stem}-audit.json"
    sheet = outdir / f"{stem}-sheet.png"
    thumb = outdir / f"{stem}-thumb.png"

    overview_path = outdir / f"{stem}-overview.png"
    try:
        if args.thumb_width <= 0:
            raise ValueError('--thumb-width must be positive')
        with render_png.OutputTransaction([png, audit_path, slices, sheet, thumb, overview_path], html) as tx:
            stats = render_png.build(html, tx.path(png), args.width, args.scale,
                                     tx.path(audit_path), tx.path(slices))
            audit = json.loads(tx.path(audit_path).read_text(encoding='utf-8'))
            from_sections(tx.path(slices), tx.path(sheet))
            with Image.open(tx.path(png)) as im:
                tw = args.thumb_width
                th = max(1, round(im.height * tw / im.width))
                with im.resize((tw, th), Image.Resampling.LANCZOS) as thumbnail:
                    thumbnail.save(tx.path(thumb), 'PNG')
            overview(tx.path(png), tx.path(overview_path), cols=3, section_px=1600)
            for derived in (sheet, thumb, overview_path):
                render_png.validate_png(tx.path(derived))
            tx.commit()
        stats['png'] = str(png)
        print(json.dumps(stats))
    except Exception as error:
        print(f'RENDER FAILED: {error}', file=sys.stderr)
        raise SystemExit(2)

    report, p1 = compact_report(audit)
    print()
    print("=" * 72)
    print(report)
    print("=" * 72)
    print(f"PNG      {png}  {tuple(stats['size'])}")
    print(f"SHEET    {sheet}   <- read this one image first")
    print(f"THUMB    {thumb}")
    print(f"SECTIONS {slices}/")
    print(f"AUDIT    {audit_path}")
    sys.exit(1 if p1 else 0)


if __name__ == "__main__":
    main()
