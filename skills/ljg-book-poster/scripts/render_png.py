#!/usr/bin/env python3
"""Render a single-file HTML book poster to a full-page PNG.

Usage:
    python render_png.py input.html output.png

Primary path: Playwright + Chromium full-page screenshot.
Fallback: fixed CSS-pixel vertical slices + lossless Pillow stitching.

This script intentionally avoids PDF pagination because page reflow can create
repeated content, seams, clipped rounded corners, and layout discontinuities.
"""

from __future__ import annotations

import argparse
import http.server
import os
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


def find_chromium() -> str | None:
    for candidate in (
        os.environ.get("CHROMIUM_PATH"),
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def serve(directory: Path):
    port = free_port()

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(directory), **kwargs)
    server = socketserver.TCPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def render_playwright(html: Path, output: Path, width: int, scale: float) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False

    chromium = find_chromium()
    server, port = serve(html.parent)
    try:
        with sync_playwright() as p:
            launch_kwargs = {"headless": True, "args": ["--no-sandbox"]}
            if chromium:
                launch_kwargs["executable_path"] = chromium
            browser = p.chromium.launch(**launch_kwargs)
            page = browser.new_page(viewport={"width": width, "height": 1200}, device_scale_factor=scale)
            page.goto(f"http://127.0.0.1:{port}/{html.name}", wait_until="networkidle")
            page.evaluate("document.querySelectorAll('[data-export-ignore]').forEach(x => x.style.display='none')")
            page.screenshot(path=str(output), full_page=True)
            browser.close()
        return output.exists() and output.stat().st_size > 0
    except Exception as exc:
        print(f"full-page render failed: {exc}", file=sys.stderr)
        return False
    finally:
        server.shutdown()
        server.server_close()


def render_sliced(html: Path, output: Path, width: int, slice_height: int, scale: float) -> None:
    try:
        from playwright.sync_api import sync_playwright
        from PIL import Image
    except Exception as exc:
        raise SystemExit(f"Fallback requires playwright and Pillow: {exc}")

    chromium = find_chromium()
    server, port = serve(html.parent)
    tmpdir = Path(tempfile.mkdtemp(prefix="book-poster-slices-"))
    try:
        with sync_playwright() as p:
            launch_kwargs = {"headless": True, "args": ["--no-sandbox"]}
            if chromium:
                launch_kwargs["executable_path"] = chromium
            browser = p.chromium.launch(**launch_kwargs)
            page = browser.new_page(viewport={"width": width, "height": slice_height}, device_scale_factor=scale)
            page.goto(f"http://127.0.0.1:{port}/{html.name}", wait_until="networkidle")
            page.evaluate("document.querySelectorAll('[data-export-ignore]').forEach(x => x.style.display='none')")
            total_height = int(page.evaluate("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"))

            paths: list[Path] = []
            y = 0
            idx = 0
            while y < total_height:
                h = min(slice_height, total_height - y)
                page.evaluate(f"window.scrollTo(0, {y})")
                page.wait_for_timeout(50)
                path = tmpdir / f"slice-{idx:04d}.png"
                page.screenshot(path=str(path), clip={"x": 0, "y": y, "width": width, "height": h})
                paths.append(path)
                y += h
                idx += 1
            browser.close()

        images = [Image.open(p).convert("RGB") for p in paths]
        stitched = Image.new("RGB", (images[0].width, sum(im.height for im in images)), "white")
        yy = 0
        for im in images:
            stitched.paste(im, (0, yy))
            yy += im.height
        stitched.save(output, "PNG", optimize=True)
    finally:
        server.shutdown()
        server.server_close()
        for p in tmpdir.glob("*"):
            p.unlink(missing_ok=True)
        tmpdir.rmdir()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input_html", type=Path)
    ap.add_argument("output_png", type=Path)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--slice-height", type=int, default=3200)
    args = ap.parse_args()

    html = args.input_html.resolve()
    output = args.output_png.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    if not html.exists():
        raise SystemExit(f"Input HTML not found: {html}")

    if not render_playwright(html, output, args.width, args.scale):
        print("Falling back to CSS-pixel slices + lossless stitching", file=sys.stderr)
        render_sliced(html, output, args.width, args.slice_height, args.scale)

    print(output)


if __name__ == "__main__":
    main()
