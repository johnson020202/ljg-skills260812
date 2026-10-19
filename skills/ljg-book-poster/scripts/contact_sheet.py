#!/usr/bin/env python3
"""Build one overview image from a rendered poster: phone-thumb strip + label.

Replaces the old "crop a region, Read it, guess pixel offsets, crop again" loop.
One Read of the contact sheet shows the whole poster at readable size.

Usage:
    python3 contact_sheet.py poster.png --out sheet.png [--cols 3] [--section-px 1600]
    python3 contact_sheet.py poster.png --out sheet.png --sections slices/
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
)


def font_candidates():
    windows = Path(os.environ.get('WINDIR') or os.environ.get('SystemRoot') or 'C:/Windows')
    # CJK-capable bundled fallback; Arial cannot guarantee Chinese label glyphs.
    bundled = Path(__file__).resolve().parents[1] / 'assets/fonts/LXGWWenKai-Regular.ttf'
    return (str(windows / 'Fonts/msyh.ttc'), *FONT_CANDIDATES, str(bundled))


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in font_candidates():
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def label_strip(draw, xy, text, fnt, fill=(255, 255, 255), bg=(0, 0, 0)):
    x, y = xy
    box = draw.textbbox((0, 0), text, font=fnt)
    w, h = box[2] - box[0], box[3] - box[1]
    draw.rectangle([x, y, x + w + 16, y + h + 12], fill=bg)
    draw.text((x + 8, y + 4), text, font=fnt, fill=fill)


def overview(png: Path, out: Path, cols: int, section_px: int):
    if cols <= 0 or section_px <= 0:
        raise ValueError('cols and section_px must be positive')
    with Image.open(png) as source:
        im = source.convert('RGB')
    W, H = im.size
    rows = max(1, (H + section_px - 1) // section_px)
    cols = max(1, min(cols, rows))
    rows = (rows + cols - 1) // cols
    cell_w = max(1, W // cols)
    cell_h = max(1, round(min(section_px, H) * cell_w / W))
    gap = 18
    sheet = Image.new("RGB", (cols * cell_w + (cols + 1) * gap, rows * cell_h + (rows + 1) * gap), (28, 28, 30))
    draw = ImageDraw.Draw(sheet)
    fnt = font(34)
    for i in range(rows * cols):
        y0 = i * section_px
        if y0 >= H:
            break
        y1 = min(H, y0 + section_px)
        tile = im.crop((0, y0, W, y1)).resize((cell_w, max(1, round((y1 - y0) * cell_w / W))), Image.Resampling.LANCZOS)
        cx = gap + (i % cols) * (cell_w + gap)
        cy = gap + (i // cols) * (cell_h + gap)
        sheet.paste(tile, (cx, cy))
        label_strip(draw, (cx + 6, cy + 6), f"{i + 1}/{rows * cols}  y={y0}", fnt)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "PNG", optimize=True)
    print(json.dumps({"sheet": str(out), "size": list(sheet.size), "tiles": min(rows * cols, (H + section_px - 1) // section_px)}))


def from_sections(slice_dir: Path, out: Path):
    """All section crops in one column, each labeled, scaled to a readable width."""
    manifest = json.loads((slice_dir / '_sections.json').read_text(encoding='utf-8'))
    files = []
    for section in manifest:
        name = section.get('file', section['name'] + '.png')
        if Path(name).name != name or not name.endswith('.png'):
            raise ValueError(f'Invalid section filename: {name}')
        path = slice_dir / name
        if path.resolve().parent != slice_dir.resolve():
            raise ValueError(f'Section escapes directory: {name}')
        files.append(path)
    if not files:
        raise ValueError(f'no section crops in {slice_dir}')
    width = 760
    fnt = font(30)
    tiles = []
    for f in files:
        with Image.open(f) as source:
            scale = width / source.width
            im = source.convert('RGB').resize((width, max(1, int(source.height * scale))), Image.Resampling.LANCZOS)
        tiles.append((f.stem, im))
    pad = 14
    total_h = sum(t.height + 44 + pad for _, t in tiles) + pad
    sheet = Image.new("RGB", (width + pad * 2, total_h), (24, 24, 26))
    draw = ImageDraw.Draw(sheet)
    y = pad
    for name, tile in tiles:
        draw.text((pad, y), name, font=fnt, fill=(255, 210, 120))
        y += 40
        sheet.paste(tile, (pad, y))
        y += tile.height + pad
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "PNG", optimize=True)
    print(json.dumps({"sheet": str(out), "size": list(sheet.size), "sections": len(tiles)}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("png", type=Path)
    ap.add_argument("--out", type=Path, default=Path("contact_sheet.png"))
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--section-px", type=int, default=1600)
    ap.add_argument("--sections", type=Path, default=None, help="build from per-section crops instead")
    args = ap.parse_args()
    if args.sections:
        from_sections(args.sections, args.out)
    else:
        overview(args.png, args.out, args.cols, args.section_px)


if __name__ == "__main__":
    main()
