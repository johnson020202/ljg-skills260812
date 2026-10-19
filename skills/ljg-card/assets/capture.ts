#!/usr/bin/env bun

import { mkdtemp, realpath, rename, rm, stat, writeFile } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { joinPngStrips } from "./png-strips";

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const [htmlPath, outputPath] = args;
  const width = Number(args[2] ?? 1200);
  const height = Number(args[3] ?? 1600);
  const fullpage = args[4] === "fullpage";
  const timeout = Number(process.env.CAPTURE_TIMEOUT_MS ?? 15000);
  if (!htmlPath || !outputPath) throw new Error("Usage: bun assets/capture.ts <html> <png> [width] [height] [fullpage]");
  if (![width, height, timeout].every(value => Number.isSafeInteger(value) && value > 0) || timeout > 120000) throw new Error("Dimensions and CAPTURE_TIMEOUT_MS must be positive integers (timeout <= 120000)");
  const resolvedHtml = await realpath(resolve(htmlPath));
  const resolvedOutput = resolve(outputPath);
  const inputStat = await stat(resolvedHtml);
  const outputStat = await stat(resolvedOutput).catch(error => {
    if (error.code === "ENOENT") return null;
    throw error;
  });
  if (outputStat && inputStat.dev === outputStat.dev && inputStat.ino === outputStat.ino) throw new Error("Output must not alias input HTML");
  const logoUrl = pathToFileURL(resolve(import.meta.dir, "logo.png")).href;

  let chromium: typeof import("playwright").chromium;
  try { ({ chromium } = await import("playwright")); }
  catch { throw new Error("Playwright not found. Run: bun install && bunx playwright install chromium"); }

  const browser = await chromium.launch({ timeout });
  let png: Buffer;
  try {
    // Keep the original 800px fullpage layout viewport throughout measurement/capture.
    const page = await browser.newPage({ viewport: { width, height: fullpage ? 800 : height }, deviceScaleFactor: 1 });
    page.setDefaultTimeout(timeout);
    await page.goto(pathToFileURL(resolvedHtml).href, { waitUntil: "domcontentloaded", timeout });
    await page.evaluate(async ({ logoUrl, timeout }) => {
      const images = Array.from(document.images).filter(image => !image.closest('[data-state="empty"]'));
      for (const image of images) {
        // Only mutate the loaded DOM. Relative references keep the original document URL.
        if (image.getAttribute("src") === "{{LOGO}}") image.src = logoUrl;
        image.loading = "eager";
      }
      const pending = new Set(images);
      let fontsPending = true;
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([
          Promise.all([
            document.fonts.ready.then(() => { fontsPending = false; }),
            ...images.map(async image => {
              try { await image.decode(); }
              catch { throw new Error(`Image failed: ${image.currentSrc || image.src}`); }
              pending.delete(image);
              if (!image.complete || !image.naturalWidth) throw new Error(`Broken image: ${image.src}`);
              if (!image.closest(".author, .who") && !image.alt.trim()) throw new Error(`Missing semantic alt: ${image.src}`);
            }),
          ]),
          new Promise<never>((_, reject) => {
            timer = setTimeout(() => reject(new Error(`Resource timeout (${timeout}ms): ${[...pending].map(image => image.currentSrc || image.src).join(", ")}${fontsPending ? "; fonts pending" : ""}`)), timeout);
          }),
        ]);
      } finally { clearTimeout(timer); }
      const failedFonts = Array.from(document.fonts).filter(font => font.status === "error");
      if (failedFonts.length) throw new Error(`Fonts failed: ${failedFonts.map(font => font.family).join(", ")}`);
    }, { logoUrl, timeout });

    const captureHeight = fullpage ? await page.evaluate(() => Math.ceil(Math.max(
      document.body.scrollHeight, document.body.offsetHeight,
      document.documentElement.scrollHeight, document.documentElement.offsetHeight,
    ))) : height;
    if (width * captureHeight > 64_000_000) throw new Error("Screenshot exceeds the 64 megapixel budget");
    const strips: Buffer[] = [];
    // 4096 CSS px at 1x avoids oversized compositor textures without resizing layout.
    for (let y = 0; y < captureHeight; y += 4096) {
      strips.push(await page.screenshot({
        type: "png", fullPage: fullpage, animations: "disabled", timeout,
        clip: { x: 0, y, width, height: Math.min(4096, captureHeight - y) },
      }));
    }
    png = strips.length === 1 ? strips[0] : joinPngStrips(strips, width, captureHeight);
  } finally { await browser.close(); }

  // Publish only after every resource, tile, and encoding succeeded. Rename on the same
  // filesystem preserves the prior output on failure; the temporary directory is private.
  const staging = await mkdtemp(join(dirname(resolvedOutput), ".capture-"));
  try {
    const temporary = join(staging, basename(resolvedOutput));
    await writeFile(temporary, png);
    await rename(temporary, resolvedOutput);
  } finally { await rm(staging, { recursive: true, force: true }); }
  console.log(`OK: ${resolvedOutput}`);
}

if (import.meta.main) main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
