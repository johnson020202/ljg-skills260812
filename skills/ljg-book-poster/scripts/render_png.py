#!/usr/bin/env python3
"""Render a single-file HTML book poster to a full-page PNG, fast and seam-free.

Key properties (all verified on 2026-10-17):
  * One browser launch, one page load, no scrolling.
  * CDP Page.captureScreenshot with captureBeyondViewport + clip.scale. Chrome
    renders the clip at the requested scale natively, so output is as sharp as
    device_scale_factor=2 while never triggering the ~16384px single-shot cap.
  * Slices are cut in CSS pixel coordinates and stitched losslessly; slices are
    byte-identical to a single-shot capture at the same scale (verified).
  * The audit step runs in the same session, so no second browser launch.

Usage:
    python3 render_png.py book.html out.png [--width 1440] [--scale 2]
    python3 render_png.py book.html out.png --audit audit.json
    python3 render_png.py book.html out.png --slices out/slice   # section crops
"""
from __future__ import annotations

import argparse
import base64
import http.server
import io
import json
import os
import socketserver
import sys
import threading
import time
from pathlib import Path

from PIL import Image as _PILImage

# Long posters routinely exceed PIL's 179M-pixel "decompression bomb" guard
# (a 1440x30000 CSS page at 2x is ~173M px; taller pages trip it). The pixels
# are ours — raise the cap.
_PILImage.MAX_IMAGE_PIXELS = None

SLICE_CSS = 6000  # CSS px per CDP capture; well under Chrome's 16384 device-px cap
AUDIT_JS = Path(__file__).with_name("audit.js")


def find_chromium() -> str | None:
    for candidate in (
        os.environ.get("CHROMIUM_PATH"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def serve(directory: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    handler = lambda *a, **k: Quiet(*a, directory=str(directory), **k)
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def capture(cdp, y: int, h: int, width: int, scale: float):
    from PIL import Image

    data = cdp.send(
        "Page.captureScreenshot",
        {
            "format": "png",
            "captureBeyondViewport": True,
            "clip": {"x": 0, "y": y, "width": width, "height": h, "scale": scale},
        },
    )["data"]
    return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")


def page_height(page) -> int:
    return int(
        page.evaluate(
            "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight,"
            " document.querySelector('#poster') ? document.querySelector('#poster').scrollHeight : 0)"
        )
    )


def render(
    html: Path,
    out: Path,
    width: int,
    scale: float,
    audit_out: Path | None,
    slice_dir: Path | None,
    sheet: Path | None = None,
):
    from playwright.sync_api import sync_playwright
    from PIL import Image

    chromium = find_chromium()
    server = serve(html.parent)
    port = server.server_address[1]
    t0 = time.time()
    try:
        with sync_playwright() as p:
            launch = {"headless": True, "args": ["--no-sandbox", "--hide-scrollbars", "--force-color-profile=srgb"]}
            if chromium:
                launch["executable_path"] = chromium
            browser = p.chromium.launch(**launch)
            page = browser.new_page(viewport={"width": width, "height": 1200}, device_scale_factor=1)
            page.goto(f"http://127.0.0.1:{port}/{html.name}", wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(250)
            page.evaluate(
                "document.querySelectorAll('[data-export-ignore]').forEach(x => x.style.display='none')"
            )
            total = page_height(page)
            if total < 10:
                raise SystemExit("页面高度异常（<10px），检查 HTML 是否有固定高度或 display:none")

            cdp = page.context.new_cdp_session(page)

            # ---- optional section crops (for QA), from the same loaded page ----
            if slice_dir:
                slice_dir.mkdir(parents=True, exist_ok=True)
                info = page.evaluate((AUDIT_JS).read_text())
                for sec in info["sections"]:
                    pad = 12
                    y = max(0, sec["y"] - pad)
                    h = min(total - y, sec["h"] + pad * 2)
                    if h <= 0:
                        continue
                    img = capture(cdp, y, h, width, scale)
                    img.save(slice_dir / f"{sec['name']}.png", optimize=True)
                (slice_dir / "_sections.json").write_text(json.dumps(info["sections"], ensure_ascii=False, indent=1))

            # ---- slices ----
            t_cap = time.time()
            parts = []
            y = 0
            while y < total:
                h = min(SLICE_CSS, total - y)
                parts.append(capture(cdp, y, h, width, scale))
                y += h
            cap_s = time.time() - t_cap

            # ---- audit in the same session ----
            if audit_out:
                audit_out.parent.mkdir(parents=True, exist_ok=True)
                audit_out.write_text(json.dumps(page.evaluate((AUDIT_JS).read_text()), ensure_ascii=False, indent=1))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    if len(parts) == 1:
        out.parent.mkdir(parents=True, exist_ok=True)
        parts[0].save(out, "PNG", optimize=True)
    else:
        stitched = Image.new("RGB", (parts[0].width, sum(p.height for p in parts)), "white")
        top = 0
        for part in parts:
            stitched.paste(part, (0, top))
            top += part.height
        out.parent.mkdir(parents=True, exist_ok=True)
        stitched.save(out, "PNG", optimize=True)

    if sheet and slice_dir:
        sys.path.insert(0, str(Path(__file__).parent))
        from contact_sheet import from_sections

        from_sections(slice_dir, sheet)

    size = Image.open(out).size
    print(
        json.dumps(
            {
                "png": str(out),
                "size": list(size),
                "cssHeight": total,
                "slices": len(parts),
                "captureSeconds": round(cap_s, 2),
                "totalSeconds": round(time.time() - t0, 2),
            }
        )
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input_html", type=Path)
    ap.add_argument("output_png", type=Path)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--audit", type=Path, default=None, help="write layout audit JSON here")
    ap.add_argument("--slices", type=Path, default=None, help="write per-section crops to this directory")
    ap.add_argument("--sheet", type=Path, default=None, help="write one contact sheet of all sections here")
    args = ap.parse_args()

    html = args.input_html.resolve()
    if not html.exists():
        raise SystemExit(f"Input HTML not found: {html}")
    render(
        html,
        args.output_png.resolve(),
        args.width,
        args.scale,
        args.audit.resolve() if args.audit else None,
        args.slices.resolve() if args.slices else None,
        args.sheet.resolve() if args.sheet else None,
    )


if __name__ == "__main__":
    main()
