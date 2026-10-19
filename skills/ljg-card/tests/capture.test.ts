import { afterAll, beforeAll, expect, test } from "bun:test";
import { link, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium, type Browser } from "playwright";

const capturePath = resolve(import.meta.dir, "../assets/capture.ts");
const logoPath = resolve(import.meta.dir, "../assets/logo.png");
const directory = await mkdtemp(join(tmpdir(), "card-capture-test-"));
let browser: Browser;
beforeAll(async () => { browser = await chromium.launch(); });
afterAll(async () => { await browser?.close(); await rm(directory, { recursive: true, force: true }); });

async function run(name: string, html: string, fullpage = true, timeout = "10000") {
  const input = join(directory, `${name}.html`);
  const output = join(directory, `${name}.png`);
  await writeFile(input, html);
  const child = Bun.spawn([process.execPath, capturePath, input, output, "1080", "800", ...(fullpage ? ["fullpage"] : [])], {
    env: { ...process.env, CAPTURE_TIMEOUT_MS: timeout }, stdout: "pipe", stderr: "pipe",
    timeout: timeout === "1200" ? 8000 : 25000,
  });
  const [exitCode, stdout, stderr] = await Promise.all([child.exited, new Response(child.stdout).text(), new Response(child.stderr).text()]);
  expect(await readFile(input, "utf8")).toBe(html);
  return { output, exitCode, stdout, stderr };
}

// Independent browser image decoder: these assertions do not use the stitcher's PNG code.
async function pixels(path: string, points: [number, number][]) {
  const page = await browser.newPage();
  try {
    const src = `data:image/png;base64,${(await readFile(path)).toString("base64")}`;
    return await page.evaluate(async ({ src, points }) => {
      const image = new Image();
      image.src = src;
      await image.decode();
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 1;
      const context = canvas.getContext("2d")!;
      return { width: image.width, height: image.height, colors: points.map(([x, y]) => {
        context.clearRect(0, 0, 1, 1);
        context.drawImage(image, x, y, 1, 1, 0, 0, 1, 1);
        return [...context.getImageData(0, 0, 1, 1).data];
      }) };
    }, { src, points });
  } finally { await page.close(); }
}
const baseStyle = "<style>*{margin:0;box-sizing:border-box}html,body{width:1080px}</style>";

test("VIS-01: 100vh + fixed body preserves the bottom END sentinel", async () => {
  const result = await run("height-change", `${baseStyle}<section style="height:100vh;background:#ddd">100vh</section><main style="height:1000px;background:#eee;display:flex;align-items:flex-end"><div style="height:100px;width:100%;background:#b00">END SENTINEL</div></main>`);
  expect(result.exitCode).toBe(0);
  expect(await pixels(result.output, [[800, 750], [800, 850], [800, 1750]])).toEqual({ width: 1080, height: 1800, colors: [[221, 221, 221, 255], [238, 238, 238, 255], [187, 0, 0, 255]] });
}, 30000);

test("VIS-03: offscreen lazy image is actively loaded across multiple fixed-viewport tiles", async () => {
  const result = await run("lazy", `${baseStyle}<div style="height:20000px;background:linear-gradient(#ffffff,#000000)">spacer</div><img style="display:block;width:100px;height:100px" loading="lazy" src="${logoPath}" alt="lazy logo"><div style="height:100px;background:#b00">END</div>`);
  expect(result.exitCode).toBe(0);
  const image = await pixels(result.output, [[800, 16000], [800, 19999], [800, 20150]]);
  expect(image.height).toBe(20200);
  expect(image.colors[0][0]).toBeLessThan(70);
  expect(image.colors[1][0]).toBeLessThan(5);
  expect(image.colors[2]).toEqual([187, 0, 0, 255]);
}, 30000);

test("fixed canvas dimensions and LOGO replacement never rewrite input HTML", async () => {
  const result = await run("logo", `${baseStyle}<img src="{{LOGO}}" alt="brand" style="width:50px;height:50px">`, false);
  expect(result.exitCode).toBe(0);
  const image = await pixels(result.output, [[900, 700]]);
  expect([image.width, image.height]).toEqual([1080, 800]);
}, 30000);

test("missing/broken image fails without replacing the previous PNG", async () => {
  const old = Buffer.from("previous successful image");
  await writeFile(join(directory, "broken.png"), old);
  const result = await run("broken", `${baseStyle}<img loading="lazy" src="missing.png" alt="missing">`);
  expect(result.exitCode).not.toBe(0);
  expect(result.stderr).toMatch(/image|Image/);
  expect(await readFile(result.output)).toEqual(old);
}, 30000);

test("a never-ending image request is bounded and names the pending resource", async () => {
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch() { return new Promise<Response>(() => {}); } });
  try {
    const old = Buffer.from("previous image");
    await writeFile(join(directory, "hanging.png"), old);
    const started = Date.now();
    const result = await run("hanging", `${baseStyle}<div style="height:20000px"></div><img loading="lazy" src="http://127.0.0.1:${server.port}/never.png" alt="pending">`, true, "1200");
    expect(result.exitCode).not.toBe(0);
    expect(Date.now() - started).toBeLessThan(10000);
    expect(result.stderr).toContain("never.png");
    expect(await readFile(result.output)).toEqual(old);
  } finally { server.stop(true); }
}, 15000);

test("output may not alias the input HTML by path, symlink, or hard link", async () => {
  const input = join(directory, "same.html");
  const html = `${baseStyle}<p>must survive</p>`;
  await writeFile(input, html);
  const symbolic = join(directory, "symbolic.html");
  const hard = join(directory, "hard.html");
  await symlink(input, symbolic);
  await link(input, hard);
  for (const output of [input, symbolic, hard]) {
    const child = Bun.spawn([process.execPath, capturePath, input, output], { stdout: "pipe", stderr: "pipe", timeout: 5000 });
    expect(await child.exited).not.toBe(0);
    expect(await readFile(input, "utf8")).toBe(html);
  }
}, 30000);
