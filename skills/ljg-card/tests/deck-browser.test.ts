import { afterAll, beforeAll, expect, test } from "bun:test";
import { resolve } from "node:path";
import { chromium, type Browser } from "playwright";
import { materializeTemplate, validateHtml } from "../../ljg-present/Tools/ValidateDeck";

const template = await Bun.file(resolve(import.meta.dir, "../../ljg-present/SloganTemplate.html")).text();
let browser: Browser;
beforeAll(async () => { browser = await chromium.launch(); });
afterAll(async () => { await browser?.close(); });

// Actual execution smoke test, complementary to ValidateDeck's static template contract.
test.each(["black", "hacker", "hacker-dark"])("materialized %s deck loads offline and navigates with correct math", async theme => {
  const html = materializeTemplate(template, theme, [
    { lines: [{ chunks: [{ t: "$x^2+y$" }] }] },
    { lines: [{ chunks: [{ t: "$x_1a$" }] }] },
    { lines: [{ chunks: [{ t: "来源 https://example.invalid/ 代码 element.animate([])" }] }] },
  ]);
  expect((await validateHtml(html, { template: false, theme })).filter(check => !check.pass)).toEqual([]);
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  const errors: string[] = [];
  const requests: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/*", route => { requests.push(route.request().url()); return route.abort(); });
  try {
    await page.setContent(html, { waitUntil: "load" });
    expect(await page.locator(".slide").count()).toBe(4);
    expect(await page.locator(".math").nth(0).innerHTML()).toBe("x<sup>2</sup>+y");
    expect(await page.locator(".math").nth(1).innerHTML()).toBe("x<sub>1</sub>a");
    await page.keyboard.press("ArrowRight");
    expect(await page.locator("#pager").innerText()).toContain("02");
    expect(errors).toEqual([]);
    expect(requests).toEqual([]);
  } finally { await page.close(); }
}, 30000);
