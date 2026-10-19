import { describe, expect, spyOn, test } from "bun:test";
import { link, mkdir, mkdtemp, open, readdir, readlink, realpath, rename, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { deflateSync } from "node:zlib";
import { chromium } from "playwright";
import sharp from "sharp";
import { ArtifactTransaction, preflightArtifacts } from "./ArtifactTransaction.ts";
import {
  annotationCoverage,
  IMAGE_LIMITS,
  clearGeneratedSlices,
  readHeroDataUri,
  readPngDimensions,
  renderHtml,
  sha256File,
  validateSpec,
} from "./RenderClassic.ts";
import { validateClassicArtifacts } from "./ValidateClassic.ts";

const validSpec = {
  book: "道德经",
  chapter: "第十六章",
  original: "致虚极，守静笃。",
  source: "通行本",
  passages: [{
    tokens: [
      { text: "致虚极", note: "尽力使内心虚静", tone: "word" },
      { text: "，", punctuation: true },
      { text: "守静笃", note: "彻底守住清静", tone: "clause" },
      { text: "。", punctuation: true },
    ],
  }],
  interpretation: ["先让心静下来，才看得见事物如何往复。"],
};

describe("validateSpec", () => {
  test("accepts a fully annotated round-trip spec", () => {
    const spec = validateSpec(validSpec);
    expect(spec.book).toBe("道德经");
  });

  test("rejects an unannotated non-punctuation token", () => {
    const broken = structuredClone(validSpec) as any;
    delete broken.passages[0].tokens[0].note;
    expect(() => validateSpec(broken)).toThrow("note must be a non-empty string");
  });

  test("rejects original round-trip drift", () => {
    const broken = structuredClone(validSpec) as any;
    broken.original = "致虚极。";
    expect(() => validateSpec(broken)).toThrow("Original round-trip mismatch");
  });

  test("rejects annotation fields on punctuation", () => {
    const broken = structuredClone(validSpec) as any;
    broken.passages[0].tokens[1].note = "逗号";
    expect(() => validateSpec(broken)).toThrow("is punctuation");
  });

  test("rejects a non-boolean punctuation flag", () => {
    const broken = structuredClone(validSpec) as any;
    broken.passages[0].tokens[0].punctuation = "yes";
    expect(() => validateSpec(broken)).toThrow("punctuation must be a boolean");
  });

  test("accepts a local hero image with paired alt text", () => {
    const spec = validateSpec({
      ...validSpec,
      heroImage: "assets/chapter-hero.png",
      heroAlt: "雾山静水间，一圈涟漪正在平复",
    });
    expect(spec.heroImage).toBe("assets/chapter-hero.png");
  });

  test("rejects a hero image without alt text", () => {
    expect(() => validateSpec({ ...validSpec, heroImage: "assets/chapter-hero.png" }))
      .toThrow("heroAlt must be a non-empty string");
  });

  test("rejects remote and data hero sources", () => {
    for (const heroImage of ["https://example.com/hero.png", "data:image/png;base64,AAAA"]) {
      expect(() => validateSpec({ ...validSpec, heroImage, heroAlt: "章节意旨图" }))
        .toThrow("heroImage must be a local file path");
    }
  });

  test("rejects interpretation scaffolding labels", () => {
    expect(() => validateSpec({ ...validSpec, interpretation: ["解读边界：这里只适用于某些情况。"] }))
      .toThrow("interpretation must not contain 解读边界");
  });

  test("preserves an explicit newline punctuation token in the original round trip", () => {
    const spec = validateSpec({
      ...validSpec,
      original: "致虚极。\n守静笃。",
      passages: [{
        tokens: [
          { text: "致虚极", note: "尽力使内心虚静", tone: "word" },
          { text: "。", punctuation: true },
          { text: "\n", punctuation: true },
          { text: "守静笃", note: "彻底守住清静", tone: "clause" },
          { text: "。", punctuation: true },
        ],
      }],
    });
    expect(spec.original).toBe("致虚极。\n守静笃。");
    expect(renderHtml(spec)).toContain('<br class="punctuation-break" data-token="punctuation">');
  });

  test("rejects unsupported whitespace and unsplit line breaks", () => {
    for (const token of [
      { text: " ", punctuation: true },
      { text: "\t", punctuation: true },
      { text: "\n\n", punctuation: true },
      { text: "\n", note: "换行", tone: "word" },
      { text: "致虚极\n", note: "未拆换行", tone: "word" },
      { text: "。\n", punctuation: true },
    ]) {
      const broken = structuredClone(validSpec) as any;
      broken.passages[0].tokens[0] = token;
      expect(() => validateSpec(broken)).toThrow();
    }
  });
});

describe("renderHtml", () => {
  test("escapes content and emits all semantic sections", () => {
    const spec = validateSpec({ ...validSpec, source: "通行本 <校本>" });
    const html = renderHtml(spec, 1080);
    expect(html).toContain("data-book");
    expect(html).toContain("data-chapter");
    expect(html).toContain("章节解读");
    expect(html).toContain("tone-word");
    expect(html).toContain("tone-clause");
    expect(html).toContain("&lt;校本&gt;");
    expect(html).toContain("width: 1080px");
    expect(html).toContain(
      '<span class="classic-run"><span class="classic-text">致虚极</span><span class="punctuation" data-token="punctuation">，</span></span>',
    );
  });

  test("embeds a quiet hero before the classic text and uses warm ink interpretation", () => {
    const spec = validateSpec({
      ...validSpec,
      heroImage: "assets/chapter-hero.png",
      heroAlt: "雾山静水间，一圈涟漪正在平复",
    });
    const html = renderHtml(spec, 1080, "data:image/png;base64,AAAA");
    expect(html).toContain('class="hero-image"');
    expect(html).toContain('src="data:image/png;base64,AAAA"');
    expect(html).toContain('alt="雾山静水间，一圈涟漪正在平复"');
    expect(html.indexOf('class="hero"')).toBeLessThan(html.indexOf('class="classic"'));
    expect(html).toContain("--interpretation-ink: #39342e");
    expect(html).toContain("--interpretation-paper: #eee8dc");
    expect(html).not.toContain("--blue:");
  });

  test("keeps opening punctuation with the following token across explicit line breaks", () => {
    const spec = validateSpec({
      ...validSpec,
      original: "曰：“道。”\n“德”。",
      passages: [{ tokens: [
        { text: "曰", note: "说", tone: "word" },
        { text: "：", punctuation: true },
        { text: "“", punctuation: true },
        { text: "道", note: "道路与规律", tone: "word" },
        { text: "。", punctuation: true },
        { text: "”", punctuation: true },
        { text: "\n", punctuation: true },
        { text: "“", punctuation: true },
        { text: "德", note: "所得与品格", tone: "word" },
        { text: "”", punctuation: true },
        { text: "。", punctuation: true },
      ] }],
    });
    const html = renderHtml(spec, 1080);
    expect(html).toContain(
      '<span class="classic-run"><span class="punctuation" data-token="punctuation">“</span><span class="classic-text">道</span>',
    );
    const lineBreak = html.indexOf('<br class="punctuation-break" data-token="punctuation">');
    const firstClosingQuote = html.indexOf('<span class="punctuation" data-token="punctuation">”</span>');
    const secondOpeningQuote = html.indexOf(
      '<span class="punctuation" data-token="punctuation">“</span><span class="classic-text">德</span>',
    );
    expect(firstClosingQuote).toBeLessThan(lineBreak);
    expect(lineBreak).toBeLessThan(secondOpeningQuote);
  });

  test("never reorders punctuation that appears before a line break", () => {
    const spec = validateSpec({
      ...validSpec,
      original: "曰“\n善",
      passages: [{ tokens: [
        { text: "曰", note: "说", tone: "word" },
        { text: "“", punctuation: true },
        { text: "\n", punctuation: true },
        { text: "善", note: "好", tone: "word" },
      ] }],
    });
    const html = renderHtml(spec, 1080);
    const openingQuote = html.indexOf('<span class="punctuation" data-token="punctuation">“</span>');
    const lineBreak = html.indexOf('<br class="punctuation-break" data-token="punctuation">');
    const followingToken = html.indexOf('<span class="classic-text">善</span>');
    expect(openingQuote).toBeLessThan(lineBreak);
    expect(lineBreak).toBeLessThan(followingToken);
  });

  test("keeps computed typography inside the layout grammar ranges", async () => {
    const spec = validateSpec({
      ...validSpec,
      source: "維基文庫固定修订 https://zh.wikisource.org/w/index.php?title=%E9%81%93%E5%BE%B7%E7%B6%93&oldid=2354026",
      passages: [{
        tokens: [
          { text: "致虚极", note: "尽力使内心虚静", tone: "word", pinyin: "zhì xū jí" },
          { text: "，", punctuation: true },
          { text: "守静笃", note: "彻底守住清静", tone: "clause" },
          { text: "。", punctuation: true },
        ],
      }],
    });
    const browser = await chromium.launch({ headless: true });
    try {
      const page = await browser.newPage({ viewport: { width: 1080, height: 900 } });
      await page.route(/^https?:/i, route => route.abort());
      await page.setContent(renderHtml(spec, 1080));
      const sizes = await page.evaluate(() => {
        const px = (selector: string) => Number.parseFloat(getComputedStyle(document.querySelector(selector)!).fontSize);
        return {
          book: px(".book"),
          original: px(".classic-text"),
          pinyin: px(".pinyin"),
          annotation: px(".annotation"),
          source: px(".source"),
          scrollWidth: document.documentElement.scrollWidth,
        };
      });
      expect(sizes.book).toBeGreaterThanOrEqual(54);
      expect(sizes.book).toBeLessThanOrEqual(68);
      expect(sizes.original).toBeGreaterThanOrEqual(42);
      expect(sizes.original).toBeLessThanOrEqual(52);
      expect(sizes.pinyin).toBeGreaterThanOrEqual(18);
      expect(sizes.pinyin).toBeLessThanOrEqual(22);
      expect(sizes.annotation).toBeGreaterThanOrEqual(22);
      expect(sizes.annotation).toBeLessThanOrEqual(28);
      expect(sizes.source).toBeGreaterThanOrEqual(18);
      expect(sizes.source).toBeLessThanOrEqual(22);
      expect(sizes.scrollWidth).toBe(1080);
    } finally {
      await browser.close();
    }
  });

  test("renders an explicit newline as a real visual line break", async () => {
    const spec = validateSpec({
      ...validSpec,
      original: "致虚极。\n守静笃。",
      passages: [{ tokens: [
          { text: "致虚极", note: "尽力使内心虚静", tone: "word" },
          { text: "。", punctuation: true },
          { text: "\n", punctuation: true },
          { text: "守静笃", note: "彻底守住清静", tone: "clause" },
          { text: "。", punctuation: true },
      ] }],
    });
    const browser = await chromium.launch({ headless: true });
    try {
      const page = await browser.newPage({ viewport: { width: 1080, height: 900 } });
      await page.route(/^https?:/i, route => route.abort());
      await page.setContent(renderHtml(spec, 1080));
      const layout = await page.evaluate(() => ({
        tops: Array.from(document.querySelectorAll<HTMLElement>(".token-unit"))
          .map(element => element.getBoundingClientRect().top),
        tokenCount: document.querySelectorAll("[data-token]").length,
      }));
      expect(layout.tops[1]).toBeGreaterThan(layout.tops[0]);
      expect(layout.tokenCount).toBe(5);
    } finally {
      await browser.close();
    }
  });
});

describe("readHeroDataUri", () => {
  test("rejects a missing local hero file", async () => {
    const directory = await mkdtemp(resolve(tmpdir(), "classic-missing-hero-"));
    try {
      await expect(readHeroDataUri(resolve(directory, "missing.png")))
        .rejects.toThrow("heroImage not found");
    } finally { await rm(directory, { recursive: true, force: true }); }
  });
});

describe("QA slice lifecycle", () => {
  test("removes only renderer-owned slices before a rerender", async () => {
    const directory = await mkdtemp(resolve(tmpdir(), "ljg-classic-slices-"));
    try {
      await Promise.all([
        Bun.write(resolve(directory, "01--y-0.png"), "old head"),
        Bun.write(resolve(directory, "09--y-9999.png"), "stale tail"),
        Bun.write(resolve(directory, "visual-note.png"), "keep"),
        Bun.write(resolve(directory, "README.md"), "keep"),
      ]);
      await clearGeneratedSlices(directory);
      expect(await Bun.file(resolve(directory, "01--y-0.png")).exists()).toBe(false);
      expect(await Bun.file(resolve(directory, "09--y-9999.png")).exists()).toBe(false);
      expect(await Bun.file(resolve(directory, "visual-note.png")).exists()).toBe(true);
      expect(await Bun.file(resolve(directory, "README.md")).exists()).toBe(true);
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });
});

const TEST_CRC32_TABLE = Uint32Array.from({ length: 256 }, (_, value) => {
  let crc = value;
  for (let bit = 0; bit < 8; bit += 1) crc = (crc & 1) === 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1;
  return crc >>> 0;
});

function testCrc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = TEST_CRC32_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type: string, data: Uint8Array): Buffer {
  const chunk = Buffer.alloc(12 + data.length);
  chunk.writeUInt32BE(data.length, 0);
  chunk.write(type, 4, 4, "ascii");
  Buffer.from(data).copy(chunk, 8);
  chunk.writeUInt32BE(testCrc32(chunk.subarray(4, 8 + data.length)), 8 + data.length);
  return chunk;
}

function testPng(width: number, height: number, options: { idat?: Buffer; bitDepth?: number; colorType?: number } = {}): Buffer {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = options.bitDepth ?? 8;
  ihdr[9] = options.colorType ?? 0;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", options.idat ?? deflateSync(Buffer.alloc((width + 1) * height))),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

describe("readPngDimensions", () => {
  test("accepts a complete PNG and rejects a truncated header impostor", async () => {
    const directory = await mkdtemp(resolve(tmpdir(), "ljg-classic-png-"));
    const valid = resolve(directory, "valid.png");
    const truncated = resolve(directory, "truncated.png");
    try {
      await Bun.write(valid, testPng(1080, 1200));
      const fakeHeader = new Uint8Array(24);
      fakeHeader.set([137, 80, 78, 71, 13, 10, 26, 10]);
      new DataView(fakeHeader.buffer).setUint32(16, 1080);
      new DataView(fakeHeader.buffer).setUint32(20, 1200);
      await Bun.write(truncated, fakeHeader);
      expect(await readPngDimensions(valid)).toEqual({ width: 1080, height: 1200 });
      await expect(readPngDimensions(truncated)).rejects.toThrow("is not a valid PNG");
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });
});

async function createArtifactFixture(options: { gap?: boolean } = {}) {
  const directory = await mkdtemp(resolve(tmpdir(), "ljg-classic-artifacts-"));
  const assets = resolve(directory, "assets");
  const slicesDirectory = resolve(directory, "qa-slices");
  await Promise.all([mkdir(assets, { recursive: true }), mkdir(slicesDirectory, { recursive: true })]);
  const input = resolve(directory, "classic.json");
  const html = resolve(directory, "classic.html");
  const png = resolve(directory, "classic.png");
  const manifestPath = resolve(directory, "classic.manifest.json");
  const hero = resolve(assets, "hero.png");
  const spec = validateSpec({
    ...validSpec,
    heroImage: "assets/hero.png",
    heroAlt: "山谷中一圈涟漪正在平复",
  });
  await Bun.write(input, `${JSON.stringify(spec, null, 2)}\n`);
  await Bun.write(hero, testPng(900, 600));
  await Bun.write(html, renderHtml(spec, 1080, await readHeroDataUri(hero)));
  await Bun.write(png, testPng(1080, 1200));

  const sliceOne = resolve(slicesDirectory, "01--y-0.png");
  const secondY = options.gap ? 700 : 600;
  const sliceTwo = resolve(slicesDirectory, `02--y-${secondY}.png`);
  await Bun.write(sliceOne, testPng(1080, options.gap ? 600 : 700));
  await Bun.write(sliceTwo, testPng(1080, 1200 - secondY));
  const sliceDetails = [
    { index: 1, path: sliceOne, y: 0, width: 1080, height: options.gap ? 600 : 700, sha256: await sha256File(sliceOne) },
    { index: 2, path: sliceTwo, y: secondY, width: 1080, height: 1200 - secondY, sha256: await sha256File(sliceTwo) },
  ];
  const manifest = {
    schemaVersion: 2,
    renderedAt: new Date().toISOString(),
    book: spec.book,
    chapter: spec.chapter,
    heroPresent: true,
    heroVisible: true,
    heroImagePath: hero,
    source: spec.source ?? null,
    inputPath: input,
    htmlPath: html,
    pngPath: png,
    manifestPath,
    width: 1080,
    height: 1200,
    original: spec.original,
    originalChars: Array.from(spec.original).length,
    passageCount: spec.passages.length,
    tokenCount: 4,
    punctuationCount: 2,
    annotationCount: 2,
    annotationCoverage: 1,
    toneCounts: { word: 1, clause: 1, variant: 0 },
    interpretationParagraphs: spec.interpretation.length,
    interpretationChars: Array.from(spec.interpretation.join("")).length,
    dom: {
      documentHeight: 1200,
      scrollWidth: 1080,
      tokenCount: 4,
      annotationCount: 2,
      interpretationParagraphs: 1,
      overflowCount: 0,
      clippedCount: 0,
      emptyTextCount: 0,
      titleVisible: true,
      chapterVisible: true,
      heroVisible: true,
      interpretationVisible: true,
      originalMatches: true,
      fontSizes: { book: 58, original: 46, pinyin: 20, annotation: 24, source: 20 },
    },
    qaSlices: [sliceOne, sliceTwo],
    qaSliceDetails: sliceDetails,
    sha256: {
      input: await sha256File(input),
      html: await sha256File(html),
      png: await sha256File(png),
      hero: await sha256File(hero),
    },
  };
  await Bun.write(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  return { directory, input, html, png, manifestPath, manifest, slicesDirectory };
}

async function renderCli(input: string, output: string, extra: string[] = [], browserPath?: string) {
  const child = Bun.spawn([
    process.execPath, "--no-install", resolve(import.meta.dir, "RenderClassic.ts"),
    "--input", input, "--output", output, ...extra,
  ], {
    cwd: import.meta.dir,
    env: { ...process.env, BUN_INSTALL_AUTO: "disable", ...(browserPath ? { PLAYWRIGHT_BROWSERS_PATH: browserPath } : {}) },
    stdout: "pipe", stderr: "pipe",
  });
  const [exitCode, stdout, stderr] = await Promise.all([
    child.exited, new Response(child.stdout).text(), new Response(child.stderr).text(),
  ]);
  return { exitCode, stdout, stderr };
}

// Snapshot the complete isolated tree, including link targets, not just the main PNG.
async function treeSnapshot(directory: string): Promise<Record<string, string>> {
  const files: Record<string, string> = {};
  async function visit(path: string, prefix: string) {
    for (const entry of await readdir(path, { withFileTypes: true })) {
      const key = `${prefix}${entry.name}`;
      const child = resolve(path, entry.name);
      if (entry.isSymbolicLink()) files[key] = `symlink:${await readlink(child)}`;
      else if (entry.isDirectory()) { files[`${key}/`] = "directory"; await visit(child, `${key}/`); }
      else files[key] = await sha256File(child);
    }
  }
  await visit(directory, "");
  return files;
}

describe("CLS-01 path conflicts before any write", () => {
  for (const variant of [
    "input-html", "input-png", "input-manifest", "hero-html", "hero-png", "hero-manifest",
    "html-png", "html-manifest", "normalized", "symlink-file", "symlink-parent", "hardlink",
    "case-output", "case-output-parent", "unicode-output",
    "input-in-slices", "hero-in-slices", "html-in-slices", "png-in-slices", "manifest-in-slices",
    "slices-equals-input", "slices-equals-html", "slices-symlink", "generated-symlink", "unmanaged-slice-alias",
  ]) {
    test(`CLS-01 rejects ${variant} without modifying the tree`, async () => {
      const directory = await mkdtemp(resolve(tmpdir(), "classic-conflict-"));
      try {
        const slices = resolve(directory, "slices");
        await mkdir(slices);
        let input = resolve(directory, "input.json");
        let output = resolve(directory, "out.png");
        let html = resolve(directory, "out.html");
        let slicesDir = slices;
        let hero = resolve(directory, "hero.png");
        const manifest = resolve(directory, "out.manifest.json");
        if (variant === "input-html") html = input;
        if (variant === "input-png") output = input;
        if (variant === "input-manifest") input = manifest;
        if (variant === "hero-html") html = hero;
        if (variant === "hero-png") output = hero;
        if (variant === "hero-manifest") hero = manifest;
        if (variant === "html-png") html = output;
        if (variant === "case-output") html = resolve(directory, "OUT.PNG");
        if (variant === "case-output-parent") { html = resolve(directory, "MISSING/out.png"); output = resolve(directory, "missing/OUT.PNG"); }
        if (variant === "unicode-output") { html = resolve(directory, "café.png"); output = resolve(directory, "cafe\u0301.png"); }
        if (variant === "html-manifest") html = manifest;
        if (variant === "normalized") html = `${directory}/unused/../input.json`;
        if (variant === "symlink-file") await symlink(input, html);
        if (variant === "symlink-parent") {
          await symlink(directory, resolve(directory, "alias"));
          html = resolve(directory, "alias/input.json");
        }
        if (variant === "input-in-slices") input = resolve(slices, "01--y-0.png");
        if (variant === "hero-in-slices") hero = resolve(slices, "01--y-0.png");
        if (variant === "html-in-slices") html = resolve(slices, "out.html");
        if (variant === "png-in-slices") output = resolve(slices, "out.png");
        if (variant === "manifest-in-slices") {
          // The derived manifest is outside slices only if the PNG is outside too;
          // a symlink alias gives the independent manifest collision.
          await symlink(slices, resolve(directory, "manifest-alias"));
          await symlink(resolve(slices, "manifest.json"), manifest);
        }
        if (variant === "slices-equals-input") slicesDir = input;
        if (variant === "slices-equals-html") slicesDir = html;
        if (variant === "slices-symlink") {
          slicesDir = resolve(directory, "slice-alias");
          await symlink(directory, slicesDir);
        }
        if (variant === "generated-symlink") await symlink(hero, resolve(slices, "01--y-0.png"));
        if (variant === "unmanaged-slice-alias") await Bun.write(resolve(slices, "01--Y-0.PNG"), "UNMANAGED USER FILE");
        await Bun.write(hero, testPng(2, 2));
        await Bun.write(input, JSON.stringify({ ...validSpec, heroImage: hero, heroAlt: "静水" }));
        if (variant === "hardlink") await link(input, html);
        const before = await treeSnapshot(directory);
        const result = await renderCli(input, output, ["--html", html, "--slices-dir", slicesDir], resolve(directory, "no-browser"));
        expect(result.exitCode).not.toBe(0);
        expect(await treeSnapshot(directory)).toEqual(before);
        expect(result.stderr).toMatch(/path conflict|symlink|alias/i);
      } finally { await rm(directory, { recursive: true, force: true }); }
    });
  }
});

describe("CLS-02 failed rerenders retain every artifact", () => {
  for (const failure of ["punctuation-only", "browser-launch"]) {
    test(`CLS-02 preserves the old set on ${failure}`, async () => {
      const directory = await mkdtemp(resolve(tmpdir(), "classic-rerender-"));
      try {
        const input = resolve(directory, "input.json");
        const output = resolve(directory, "out.png");
        const html = resolve(directory, "out.html");
        const slices = resolve(directory, "slices");
        await mkdir(slices);
        const spec = failure === "punctuation-only"
          ? { ...validSpec, original: "。", passages: [{ tokens: [{ text: "。", punctuation: true }] }] }
          : validSpec;
        await Bun.write(input, JSON.stringify(spec));
        for (const path of [output, html, resolve(directory, "out.manifest.json"), resolve(slices, "01--y-0.png"), resolve(slices, "09--y-9999.png"), resolve(slices, "visual-note.png")]) {
          await Bun.write(path, `OLD ${path}`);
        }
        const before = await treeSnapshot(directory);
        const result = await renderCli(input, output, ["--html", html, "--slices-dir", slices], resolve(directory, "no-browser"));
        expect(result.exitCode).not.toBe(0);
        expect(await treeSnapshot(directory)).toEqual(before);
      } finally { await rm(directory, { recursive: true, force: true }); }
    });
  }
});

describe("CLS-02 staged commit and rollback", () => {
  test("CLS-02 rolls back files, stale slices, and newly created output parents after a publish failure", async () => {
    const directory = await mkdtemp(resolve(tmpdir(), "classic-rollback-"));
    const transaction = new ArtifactTransaction();
    try {
      const html = resolve(directory, "old.html");
      const png = resolve(directory, "old.png");
      const oldSlice = resolve(directory, "slices/09--y-9999.png");
      const manifest = resolve(directory, "old.manifest.json");
      await mkdir(resolve(directory, "slices"));
      for (const path of [html, png, oldSlice, manifest]) await Bun.write(path, `OLD:${path}`);
      const before = await treeSnapshot(directory);
      await Bun.write(await transaction.stageFile(html), "NEW HTML");
      await Bun.write(await transaction.stageFile(png), "NEW PNG");
      await transaction.adopt(oldSlice); // stale slice removal is reversible too
      const newFile = resolve(directory, "new-parent/nested/new.png");
      await Bun.write(await transaction.stageFile(newFile), "NEW SLICE");
      const stagedManifest = await transaction.stageFile(manifest);
      await Bun.write(stagedManifest, "NEW MANIFEST");
      await expect(transaction.commit(async (from, to) => {
        if (from === stagedManifest) throw new Error("injected manifest install failure");
        return rename(from, to);
      })).rejects.toThrow("injected manifest install failure");
      await transaction.dispose();
      expect(await treeSnapshot(directory)).toEqual(before);
    } finally { await transaction.dispose(); await rm(directory, { recursive: true, force: true }); }
  });

  test("CLS-02 stages QA files inside an existing symlink destination, not its parent filesystem", async () => {
    const directory = await mkdtemp(resolve(tmpdir(), "classic-stage-anchor-"));
    const transaction = new ArtifactTransaction();
    try {
      const actual = resolve(directory, "mounted-volume");
      const parent = resolve(directory, "parent-volume");
      await mkdir(actual); await mkdir(parent);
      const alias = resolve(parent, "slices");
      await symlink(actual, alias);
      const scratch = await transaction.scratchDirectory(alias);
      expect(scratch.startsWith(`${await realpath(actual)}/.classic-stage-`)).toBe(true);
    } finally { await transaction.dispose(); await rm(directory, { recursive: true, force: true }); }
  });

  test("CLS-02 commits new outputs and removes only stale generated slices", async () => {
    const directory = await mkdtemp(resolve(tmpdir(), "classic-commit-"));
    const transaction = new ArtifactTransaction();
    try {
      const existing = resolve(directory, "out.png");
      const stale = resolve(directory, "09--y-9999.png");
      const keep = resolve(directory, "visual-note.png");
      await Bun.write(existing, "OLD"); await Bun.write(stale, "STALE"); await Bun.write(keep, "KEEP");
      await Bun.write(await transaction.stageFile(existing), "NEW");
      await transaction.adopt(stale);
      const newPath = resolve(directory, "fresh/nested/01--y-0.png");
      await Bun.write(await transaction.stageFile(newPath), "NEW SLICE");
      await transaction.commit(); await transaction.dispose();
      expect(await Bun.file(existing).text()).toBe("NEW");
      expect(await Bun.file(newPath).text()).toBe("NEW SLICE");
      expect(await Bun.file(keep).text()).toBe("KEEP");
      expect(await Bun.file(stale).exists()).toBe(false);
      expect(Object.keys(await treeSnapshot(directory)).some(path => path.includes(".classic-stage-"))).toBe(false);
    } finally { await transaction.dispose(); await rm(directory, { recursive: true, force: true }); }
  });

  test("CLS-01 preflight allows distinct absent outputs through a parent alias, but rejects two aliased destinations", async () => {
    const directory = await mkdtemp(resolve(tmpdir(), "classic-path-control-"));
    try {
      await mkdir(resolve(directory, "real"));
      await symlink(resolve(directory, "real"), resolve(directory, "alias"));
      const input = resolve(directory, "input.json");
      await Bun.write(input, JSON.stringify(validSpec));
      const paths = { input, html: resolve(directory, "alias/new/out.html"), png: resolve(directory, "real/new/out.png"), manifest: resolve(directory, "real/new/out.manifest.json"), slices: resolve(directory, "real/qa") };
      const before = await treeSnapshot(directory);
      expect(typeof await preflightArtifacts(paths)).toBe("string");
      await expect(preflightArtifacts({ ...paths, png: resolve(directory, "real/new/out.html") })).rejects.toThrow("Path conflict/alias");
      expect(await treeSnapshot(directory)).toEqual(before);
    } finally { await rm(directory, { recursive: true, force: true }); }
  });
});

describe("CLS-03 character-based punctuation", () => {
  for (const text of ["重要正文", "，正文", "A", "1", "😀", "〇", "。\u200b"]) {
    test(`CLS-03 rejects body text disguised as punctuation ${JSON.stringify(text)}`, () => {
      expect(() => validateSpec({ ...validSpec, original: `甲${text}。`, passages: [{ tokens: [
        { text: "甲", note: "第一", tone: "word" }, { text, punctuation: true }, { text: "。", punctuation: true },
      ] }] })).toThrow(/punctuation/);
    });
  }
  test("CLS-03 accepts Unicode punctuation and keeps all five body characters annotated", () => {
    const spec = validateSpec({ ...validSpec, original: "甲重要正文？！\n", passages: [{ tokens: [
      { text: "甲", note: "第一", tone: "word" }, { text: "重要正文", note: "正文", tone: "clause" },
      { text: "？！", punctuation: true }, { text: "\n", punctuation: true },
    ] }] });
    expect(spec.passages[0].tokens.filter(token => !token.punctuation).map(token => token.text).join("")).toBe("甲重要正文");
    expect(annotationCoverage(spec)).toBe(1);
    const forged = structuredClone(spec);
    forged.passages[0].tokens[1] = { text: "重要正文", punctuation: true };
    expect(annotationCoverage(forged)).toBe(0.2);
  });

  test("CLS-03 CLI and validator reject the original five-character coverage forgery", async () => {
    const fixture = await createArtifactFixture();
    try {
      const forged = { ...validSpec, original: "甲重要正文。", passages: [{ tokens: [
        { text: "甲", note: "第一", tone: "word" }, { text: "重要正文", punctuation: true }, { text: "。", punctuation: true },
      ] }] };
      await Bun.write(fixture.input, JSON.stringify(forged));
      fixture.manifest.sha256.input = await sha256File(fixture.input);
      await Bun.write(fixture.manifestPath, JSON.stringify(fixture.manifest));
      const before = await treeSnapshot(fixture.directory);
      await expect(validateClassicArtifacts({ input: fixture.input, png: fixture.png, manifest: fixture.manifestPath }))
        .rejects.toThrow("punctuation requires actual");
      const result = await renderCli(fixture.input, fixture.png, ["--html", fixture.html, "--slices-dir", fixture.slicesDirectory], resolve(fixture.directory, "no-browser"));
      expect(result.exitCode).toBe(1);
      expect(result.stderr).toContain("punctuation requires actual");
      expect(await treeSnapshot(fixture.directory)).toEqual(before);
    } finally { await rm(fixture.directory, { recursive: true, force: true }); }
  });
});

describe("CLS-04 schema v2 cannot downgrade by deleting fields", () => {
  for (const fields of [["dom.originalMatches"], ["dom.fontSizes"], ["qaSliceDetails"], ["dom.originalMatches", "dom.fontSizes", "qaSliceDetails"]]) {
    test(`CLS-04 requires ${fields.join(", ")}`, async () => {
      const fixture = await createArtifactFixture();
      try {
        const broken = structuredClone(fixture.manifest) as any;
        for (const field of fields) {
          if (field.startsWith("dom.")) delete broken.dom[field.slice(4)]; else delete broken[field];
        }
        await Bun.write(fixture.manifestPath, JSON.stringify(broken));
        await expect(validateClassicArtifacts({ input: fixture.input, png: fixture.png, manifest: fixture.manifestPath }))
          .rejects.toThrow(/required|must be|original order/);
      } finally { await rm(fixture.directory, { recursive: true, force: true }); }
    });
  }
  test("CLS-04 rejects modified HTML even after removing the three discriminator fields", async () => {
    const fixture = await createArtifactFixture();
    try {
      await Bun.write(fixture.html, (await Bun.file(fixture.html).text()).replace("font-size: 58px", "font-size: 1px"));
      const broken = structuredClone(fixture.manifest) as any;
      broken.sha256.html = await sha256File(fixture.html);
      delete broken.dom.originalMatches;
      delete broken.dom.fontSizes;
      delete broken.qaSliceDetails;
      await Bun.write(fixture.manifestPath, JSON.stringify(broken));
      await expect(validateClassicArtifacts({ input: fixture.input, png: fixture.png, manifest: fixture.manifestPath }))
        .rejects.toThrow("HTML differs from deterministic renderer output");
    } finally { await rm(fixture.directory, { recursive: true, force: true }); }
  });
});

describe("CLS-05 PNG must decode under a resource budget", () => {
  test("CLS-05 accepts RGBA, indexed, interlaced PNG and rejects non-PNG content", async () => {
    const directory = await mkdtemp(resolve(tmpdir(), "classic-image-controls-"));
    try {
      for (const options of [{}, { palette: true }, { progressive: true }]) {
        const path = resolve(directory, "valid.png");
        await sharp({ create: { width: 31, height: 23, channels: 4, background: { r: 90, g: 130, b: 200, alpha: 0.5 } } }).png(options).toFile(path);
        expect(await readPngDimensions(path)).toEqual({ width: 31, height: 23 });
      }
      for (const format of ["jpeg", "webp"] as const) {
        const path = resolve(directory, `hero.${format}`);
        await sharp({ create: { width: 31, height: 23, channels: 3, background: "#668899" } }).toFormat(format).toFile(path);
        expect(await readHeroDataUri(path)).toStartWith(`data:image/${format};base64,`);
        await expect(readPngDimensions(path)).rejects.toThrow("is not a valid PNG");
      }
      const fakeHero = resolve(directory, "fake.jpg");
      await Bun.write(fakeHero, "AUDIT_PRIVATE_MARKER_NOT_AN_IMAGE");
      await expect(readHeroDataUri(fakeHero)).rejects.toThrow();
    } finally { await rm(directory, { recursive: true, force: true }); }
  });

  test("CLS-05 hashes artifacts in bounded chunks rather than loading the entire file", async () => {
    const directory = await mkdtemp(resolve(tmpdir(), "classic-hash-budget-"));
    const update = spyOn(Bun.CryptoHasher.prototype, "update");
    try {
      const path = resolve(directory, "artifact.bin");
      const bytes = Buffer.alloc(2 * 1024 * 1024 + 3, 42);
      const expected = new Bun.CryptoHasher("sha256").update(bytes).digest("hex");
      update.mockClear();
      await Bun.write(path, bytes);
      expect(await sha256File(path)).toBe(expected);
      expect(update.mock.calls.length).toBeGreaterThan(1);
      expect(update.mock.calls.every(([chunk]) => typeof chunk !== "string" && chunk.byteLength <= 64 * 1024)).toBe(true);
    } finally { update.mockRestore(); await rm(directory, { recursive: true, force: true }); }
  });

  test("CLS-05 rejects oversized compressed input before reading or decoding it", async () => {
    const directory = await mkdtemp(resolve(tmpdir(), "classic-image-budget-"));
    try {
      const path = resolve(directory, "huge.png");
      const file = await open(path, "w");
      try { await file.truncate(IMAGE_LIMITS.bytes + 1); } finally { await file.close(); }
      await expect(readPngDimensions(path)).rejects.toThrow("resource budget");
    } finally { await rm(directory, { recursive: true, force: true }); }
  });

  const badCrc = testPng(2, 2);
  badCrc[29] ^= 1; // IHDR CRC
  const animationControl = Buffer.alloc(8);
  animationControl.writeUInt32BE(2, 0);
  const firstFrame = Buffer.alloc(26);
  firstFrame.writeUInt32BE(2, 4); firstFrame.writeUInt32BE(2, 8);
  firstFrame.writeUInt16BE(1, 20); firstFrame.writeUInt16BE(10, 22);
  const secondFrame = Buffer.from(firstFrame); secondFrame.writeUInt32BE(1, 0);
  const frameData = Buffer.concat([Buffer.from([0, 0, 0, 2]), deflateSync(Buffer.alloc(6))]);
  const staticPng = testPng(2, 2);
  const apng = Buffer.concat([
    staticPng.subarray(0, 33), pngChunk("acTL", animationControl), pngChunk("fcTL", firstFrame),
    staticPng.subarray(33, -12), pngChunk("fcTL", secondFrame), pngChunk("fdAT", frameData), staticPng.subarray(-12),
  ]);
  for (const [name, bytes] of [
    ["animated PNG", apng],
    ["missing IEND", testPng(2, 2).subarray(0, -12)],
    ["bad CRC", badCrc],
    ["trailing bytes", Buffer.concat([testPng(2, 2), Buffer.from("trailing")])],
    ["plaintext IDAT with correct CRC", testPng(1080, 1200, { idat: Buffer.from("not a zlib stream") })],
    ["invalid filter byte", testPng(1, 1, { idat: deflateSync(Buffer.from([5, 0])) })],
    ["missing scanline bytes", testPng(2, 2, { idat: deflateSync(Buffer.from([0, 0])) })],
    ["invalid color type", testPng(2, 2, { colorType: 1 })],
    ["invalid bit depth", testPng(2, 2, { bitDepth: 3 })],
    ["over-budget dimensions", testPng(100000, 100000, { idat: deflateSync(Buffer.from([0])) })],
    ["over-budget single side", testPng(32769, 1, { idat: deflateSync(Buffer.from([0])) })],
    ["over-budget pixel product", testPng(6000, 6000, { idat: deflateSync(Buffer.from([0])) })],
    ["truncated compressed stream", testPng(2, 2, { idat: deflateSync(Buffer.alloc(6)).subarray(0, 5) })],
  ] as const) {
    test(`CLS-05 rejects ${name}`, async () => {
      const directory = await mkdtemp(resolve(tmpdir(), "classic-bad-png-"));
      try {
        const path = resolve(directory, "bad.png");
        await Bun.write(path, bytes);
        await expect(readPngDimensions(path)).rejects.toThrow();
      } finally { await rm(directory, { recursive: true, force: true }); }
    });
  }
  for (const target of ["main", "hero", "slice"]) {
    test(`CLS-05 validator rejects undecodable ${target} even with matching hash`, async () => {
      const fixture = await createArtifactFixture();
      try {
        const path = target === "main" ? fixture.png : target === "hero" ? fixture.manifest.heroImagePath : fixture.manifest.qaSlices[0];
        const [width, height] = target === "main" ? [1080, 1200] : target === "hero" ? [900, 600] : [1080, 700];
        await Bun.write(path, testPng(width, height, { idat: Buffer.from("not a zlib stream") }));
        const hash = await sha256File(path);
        if (target === "main") fixture.manifest.sha256.png = hash;
        else if (target === "slice") fixture.manifest.qaSliceDetails[0].sha256 = hash;
        else {
          fixture.manifest.sha256.hero = hash;
          const spec = validateSpec(await Bun.file(fixture.input).json());
          await Bun.write(fixture.html, renderHtml(spec, 1080, `data:image/png;base64,${Buffer.from(await Bun.file(path).arrayBuffer()).toString("base64")}`));
          fixture.manifest.sha256.html = await sha256File(fixture.html);
        }
        await Bun.write(fixture.manifestPath, JSON.stringify(fixture.manifest));
        await expect(validateClassicArtifacts({ input: fixture.input, png: fixture.png, manifest: fixture.manifestPath })).rejects.toThrow();
      } finally { await rm(fixture.directory, { recursive: true, force: true }); }
    });
  }
});

describe("CLS browser integration", () => {
  test("CLS-01/02/03 renders, validates, and successfully replaces a complete artifact set", async () => {
    const directory = await mkdtemp(resolve(tmpdir(), "classic-e2e-"));
    try {
      const input = resolve(directory, "input.json");
      // Separate absent parents exercise sibling staging on the correct filesystem.
      const output = resolve(directory, "images/classic.png");
      const html = resolve(directory, "html/classic.html");
      const slices = resolve(directory, "qa/slices");
      const manifest = resolve(directory, "images/classic.manifest.json");
      const hero = resolve(directory, "hero.png");
      await Bun.write(hero, testPng(900, 600));
      const spec = { ...validSpec, heroImage: hero, heroAlt: "静水" };
      await Bun.write(input, JSON.stringify(spec));
      const inputHash = await sha256File(input);
      const heroHash = await sha256File(hero);
      const first = await renderCli(input, output, ["--html", html, "--slices-dir", slices]);
      expect(first.stderr).toBe("");
      expect(first.exitCode).toBe(0);
      expect(JSON.parse(first.stdout).status).toBe("rendered");
      expect((await validateClassicArtifacts({ input, png: output, manifest })).annotationCoverage).toBe(1);
      expect(await sha256File(input)).toBe(inputHash);
      expect(await sha256File(hero)).toBe(heroHash);
      const old = await Bun.file(manifest).json();
      expect(old.qaSlices.length).toBeGreaterThan(0);
      expect(old.qaSlices.every((path: string) => path.startsWith(slices))).toBe(true);
      expect(JSON.stringify(old)).not.toContain(".classic-stage-");
      await Bun.write(resolve(slices, "99--y-99999.png"), "stale generated artifact");
      await Bun.write(resolve(slices, "visual-note.png"), "keep this private note");
      await Bun.write(input, JSON.stringify({ ...spec, chapter: "另一章" }));
      const rerender = await renderCli(input, output, ["--html", html, "--slices-dir", slices]);
      expect(rerender.stderr).toBe("");
      expect(rerender.exitCode).toBe(0);
      expect((await validateClassicArtifacts({ input, png: output, manifest })).status).toBe("valid");
      expect((await Bun.file(manifest).json()).chapter).toBe("另一章");
      expect(await Bun.file(resolve(slices, "99--y-99999.png")).exists()).toBe(false);
      expect(await Bun.file(resolve(slices, "visual-note.png")).text()).toBe("keep this private note");
      expect(Object.keys(await treeSnapshot(directory)).some(path => path.includes(".classic-stage-"))).toBe(false);
    } finally { await rm(directory, { recursive: true, force: true }); }
  }, 30_000);

  test("CLS-02 preserves all old artifacts after a real DOM audit failure", async () => {
    const fixture = await createArtifactFixture();
    try {
      const text = "长".repeat(200);
      await Bun.write(fixture.input, JSON.stringify({ ...validSpec, original: text, passages: [{ tokens: [{ text, note: "过长词组", tone: "word" }] }] }));
      const before = await treeSnapshot(fixture.directory);
      const result = await renderCli(fixture.input, fixture.png, ["--html", fixture.html, "--slices-dir", fixture.slicesDirectory]);
      expect(result.exitCode).toBe(1);
      expect(result.stderr).toMatch(/DOM audit failed|Horizontal overflow/);
      expect(await treeSnapshot(fixture.directory)).toEqual(before);
    } finally { await rm(fixture.directory, { recursive: true, force: true }); }
  }, 30_000);

  test("CLS-01 supports normal extensionless output without hidden .html/.manifest paths", async () => {
    const directory = await mkdtemp(resolve(tmpdir(), "classic-extensionless-"));
    try {
      const input = resolve(directory, "input.json");
      const output = resolve(directory, "image");
      await Bun.write(input, JSON.stringify(validSpec));
      const result = await renderCli(input, output);
      expect(result.stderr).toBe("");
      expect(result.exitCode).toBe(0);
      expect((await validateClassicArtifacts({ input, png: output, manifest: `${output}.manifest.json` })).status).toBe("valid");
      expect(await Bun.file(`${output}.html`).exists()).toBe(true);
      expect(await Bun.file(resolve(directory, ".html")).exists()).toBe(false);
    } finally { await rm(directory, { recursive: true, force: true }); }
  }, 30_000);
});

describe("validateClassicArtifacts", () => {
  test("accepts a complete schema v2 artifact set", async () => {
    const fixture = await createArtifactFixture();
    try {
      const result = await validateClassicArtifacts({
        input: fixture.input,
        png: fixture.png,
        manifest: fixture.manifestPath,
      });
      expect(result.status).toBe("valid");
      expect(result.qaSlices).toBe(2);
    } finally {
      await rm(fixture.directory, { recursive: true, force: true });
    }
  });

  test("rejects schema, path, PNG dimension, HTML hash, and hero hash drift", async () => {
    const fixture = await createArtifactFixture();
    try {
      const broken = structuredClone(fixture.manifest) as any;
      broken.schemaVersion = 1;
      broken.inputPath = resolve(fixture.directory, "wrong.json");
      broken.height = 1199;
      broken.dom.fontSizes.book = 40;
      broken.sha256.html = "0".repeat(64);
      broken.sha256.hero = "f".repeat(64);
      await Bun.write(fixture.manifestPath, `${JSON.stringify(broken, null, 2)}\n`);
      await expect(validateClassicArtifacts({
        input: fixture.input,
        png: fixture.png,
        manifest: fixture.manifestPath,
      })).rejects.toThrow("manifest schemaVersion must be 2");
      await expect(validateClassicArtifacts({
        input: fixture.input,
        png: fixture.png,
        manifest: fixture.manifestPath,
      })).rejects.toThrow("inputPath mismatch");
      await expect(validateClassicArtifacts({
        input: fixture.input,
        png: fixture.png,
        manifest: fixture.manifestPath,
      })).rejects.toThrow("PNG dimension mismatch");
      await expect(validateClassicArtifacts({
        input: fixture.input,
        png: fixture.png,
        manifest: fixture.manifestPath,
      })).rejects.toThrow("computed book font size must be 54-68px");
      await expect(validateClassicArtifacts({
        input: fixture.input,
        png: fixture.png,
        manifest: fixture.manifestPath,
      })).rejects.toThrow("HTML hash mismatch");
      await expect(validateClassicArtifacts({
        input: fixture.input,
        png: fixture.png,
        manifest: fixture.manifestPath,
      })).rejects.toThrow("hero hash mismatch");
    } finally {
      await rm(fixture.directory, { recursive: true, force: true });
    }
  });

  test("rejects a QA slice coverage gap", async () => {
    const fixture = await createArtifactFixture({ gap: true });
    try {
      await expect(validateClassicArtifacts({
        input: fixture.input,
        png: fixture.png,
        manifest: fixture.manifestPath,
      })).rejects.toThrow("QA slice coverage gap before y=700");
    } finally {
      await rm(fixture.directory, { recursive: true, force: true });
    }
  });

  test("rejects stale slices and per-slice hash drift", async () => {
    const fixture = await createArtifactFixture();
    try {
      await Bun.write(resolve(fixture.slicesDirectory, "09--y-9999.png"), testPng(1080, 1));
      const broken = structuredClone(fixture.manifest) as any;
      broken.qaSliceDetails[0].sha256 = "0".repeat(64);
      await Bun.write(fixture.manifestPath, `${JSON.stringify(broken, null, 2)}\n`);
      await expect(validateClassicArtifacts({
        input: fixture.input,
        png: fixture.png,
        manifest: fixture.manifestPath,
      })).rejects.toThrow("QA slice hash mismatch");
      await expect(validateClassicArtifacts({
        input: fixture.input,
        png: fixture.png,
        manifest: fixture.manifestPath,
      })).rejects.toThrow("stale/unlisted QA slices");
    } finally {
      await rm(fixture.directory, { recursive: true, force: true });
    }
  });
});
