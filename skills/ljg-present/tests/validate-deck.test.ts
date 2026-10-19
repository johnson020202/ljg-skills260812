import { describe, expect, test } from "bun:test";
import { resolve } from "node:path";
import { materializeTemplate, validateHtml } from "../Tools/ValidateDeck";

const template = await Bun.file(resolve(import.meta.dir, "../SloganTemplate.html")).text();
function deck(text = "最小正文") {
  return materializeTemplate(template, "black", [{ lines: [{ chunks: [{ t: text }] }] }]);
}
async function failures(html: string, templateMode = false) {
  return (await validateHtml(html, { template: templateMode, theme: "black" })).filter(check => !check.pass);
}

// The eight archived card-present probe cases, now runnable without audit-directory paths.
describe("VIS-02/04/05 audit fixtures", () => {
  test("baseline", async () => expect(await failures(deck())).toEqual([]));
  test("url-literal-only", async () => expect(await failures(deck("来源 https://example.invalid/article；这只是文本。"))).toEqual([]));
  test("code-literal-only", async () => expect(await failures(deck("代码示例 element.animate([]); setInterval(callback, 1000)"))).toEqual([]));
  test("second-script-relative", async () => expect(await failures(deck().replace("</body>", '<script src="./absent-runtime.js"></script></body>'))).toContainEqual(expect.objectContaining({ id: "offline" })));
  test("second-script-syntax", async () => expect(await failures(deck().replace("</body>", "<script>const broken = ;</script></body>"))).toContainEqual(expect.objectContaining({ id: "javascript-syntax" })));
  test("second-style-motion", async () => expect(await failures(deck().replace("</head>", "<style>.slide { transition: opacity 1s; }</style></head>"))).toContainEqual(expect.objectContaining({ id: "zero-motion" })));
  test("second-style-resource", async () => expect(await failures(deck().replace("</head>", "<style>.slide { background-image: url(./absent-background.png); }</style></head>"))).toContainEqual(expect.objectContaining({ id: "offline" })));
  test("unmaterialized", async () => {
    expect(await failures(template)).toContainEqual(expect.objectContaining({ id: "unreplaced-placeholders" }));
    expect(await failures(template, true)).toEqual([]);
  });
});

describe("resource and code context", () => {
  test.each(["TITLE", "SUBTITLE", "THEME", "SLIDES_JSON", "UNEXPECTED_FIELD", " custom field "])("rejects leftover %s in finished decks", async key => {
    expect(await failures(deck(`{{${key}}}`))).toContainEqual(expect.objectContaining({ id: "unreplaced-placeholders" }));
  });
  test.each([
    '<SCRIPT defer SRC=relative.js></SCRIPT>',
    '<link rel="stylesheet" href="local.css">',
    '<img srcset="local.png 1x, other.png 2x">',
    '<object data="local.html"></object>',
    '<div style="background:url(local.png)"></div>',
    '<style media="screen">@import "local.css";</style>',
    '<script type="module">import "./local.js";</script>',
    '<iframe srcdoc="&lt;script src=local.js&gt;&lt;/script&gt;"></iframe>',
  ])("rejects actual resources: %s", async fragment => {
    expect(await failures(deck().replace("</body>", `${fragment}</body>`))).toContainEqual(expect.objectContaining({ id: "offline" }));
  });
  test.each([
    '<script>document.body.animate([])</script>',
    '<script>window.setInterval(() => {}, 1000)</script>',
    '<script>const example = `raw setInterval() ${setInterval(() => {}, 1000)}`;</script>',
    '<div style="transition:opacity 1s"></div>',
    '<style media="screen">@keyframes pulse{to{opacity:0}}</style>',
    '<script>document.body["animate"]([]);</script>',
  ])("rejects actual motion: %s", async fragment => {
    expect(await failures(deck().replace("</body>", `${fragment}</body>`))).toContainEqual(expect.objectContaining({ id: "zero-motion" }));
  });
  test("ignores prose, comments, code strings, regex literals, and CSS strings", async () => {
    const html = deck('示例 <script src="fake.js"> and .animate([])')
      .replace("</head>", '<style>.example::after{content:"url(file.png); transition:opacity 1s"}/* @import "fake.css"; */</style></head>')
      .replace("</body>", '<!-- <script src="fake.js"></script> --><script>const a = "element.animate([])"; const b = `setInterval(() => {}, 1)`; const c = /setInterval\\(/; // .animate([])\n</script><p>https://example.invalid/ setInterval()</p></body>');
    expect(await failures(html)).toEqual([]);
  });
  test("regex literals after conditions and CSS comment markers inside strings stay data", async () => {
    expect(await failures(deck().replace("</body>", '<script>if (true) /setInterval(foo)/.test("x");</script></body>'))).toEqual([]);
    expect(await failures(deck().replace("</head>", '<style>.x{content:"/*";background:url(local.png)}</style></head>'))).toContainEqual(expect.objectContaining({ id: "offline" }));
  });
  test("unfinished trailing style blocks and MIME-typed scripts are inspected", async () => {
    expect(await failures(deck() + '<style>.x{transition:opacity 1s}')).toContainEqual(expect.objectContaining({ id: "zero-motion" }));
    expect(await failures(deck().replace("</body>", '<script type="text/javascript; charset=utf-8">const broken = ;</script></body>'))).toContainEqual(expect.objectContaining({ id: "javascript-syntax" }));
  });
  test("decodes attribute entities but not raw script/style text", async () => {
    const good = deck().replace("</body>", '<div onclick="console.log(&quot;ok&quot;); return false"></div><script>const example="&quot;setInterval(foo)&quot;";</script><style>.x::after{content:"&quot;url(fake.png)&quot;"}</style></body>');
    expect(await failures(good)).toEqual([]);
    expect(await failures(deck().replace("</body>", '<div style="background:u&#114;l(local.png)"></div></body>'))).toContainEqual(expect.objectContaining({ id: "offline" }));
    expect(await failures(deck().replace("</body>", '<script type="text/java&#115;cript">const broken = ;</script></body>'))).toContainEqual(expect.objectContaining({ id: "javascript-syntax" }));
    expect(await failures(deck().replace("</body>", '<script>console.log(&quot;ok&quot;)</script></body>'))).toContainEqual(expect.objectContaining({ id: "javascript-syntax" }));
  });
  test("logical-expression and block-following regex literals are not calls", async () => {
    const html = deck().replace("</body>", '<script>const t="text"; t && /fetch(Async)?/.test(t); if(true){} /setInterval()/.test("text");</script></body>');
    expect(await failures(html)).toEqual([]);
  });
  test.each([
    '<svg><script href="relative.js"></script></svg>',
    '<svg><script xlink:href="https://example.invalid/code.js"></script></svg>',
    '<svg><filter><feImage href="relative.png" /></filter></svg>',
    '<svg><filter><feImage xlink:href="relative.png" /></filter></svg>',
    '<script>new Image().src = "https://example.invalid/pixel.png";</script>',
    '<script>const s = document.createElement("script"); s.src = "./runtime.js"; document.head.append(s);</script>',
    '<script>const image = new Image(); image["src"] = "relative.png";</script>',
  ])("rejects SVG and executable resource writes: %s", async fragment => {
    expect(await failures(deck().replace("</body>", `${fragment}</body>`))).toContainEqual(expect.objectContaining({ id: "offline" }));
  });
  test("a DOM background color assignment is not an external resource", async () => {
    expect(await failures(deck().replace("</body>", '<script>document.body.style.background = "#000";</script></body>'))).toEqual([]);
  });
  test("ordinary object src data is not a DOM resource assignment", async () => {
    expect(await failures(deck().replace("</body>", '<script>const record = {}; record.src = "来源说明";</script></body>'))).toEqual([]);
  });
  test("DOM style resource syntax remains forbidden", async () => {
    expect(await failures(deck().replace("</body>", '<script>document.body.style.background = "url(./background.png)";</script></body>'))).toContainEqual(expect.objectContaining({ id: "offline" }));
  });
  test("resource examples stay plain data, not executable references", async () => {
    const text = '来源 https://example.invalid/ 代码 new Image().src = "https://example.invalid/pixel"; script.src = "relative.js"';
    expect(await failures(deck(text))).toEqual([]);
    expect(await failures(deck().replace("</body>", '<script>const example="new Image().src = url"; const record={src:"https://example.invalid/data"};</script></body>'))).toEqual([]);
  });
  test.each(['with ({}) {}', 'return 1;', 'new.target;'])("enforces module grammar: %s", async source => {
    expect(await failures(deck().replace("</body>", `<script type="module">${source}</script></body>`))).toContainEqual(expect.objectContaining({ id: "javascript-syntax" }));
  });
  test("Script, Module and handler syntax use their real parse goals", async () => {
    expect(await failures(deck().replace("</body>", '<script>with ({}) {}</script><script type="module">export const value = await Promise.resolve(1);</script><button onclick="return false"></button></body>'))).toEqual([]);
    expect(await failures(deck().replace("</body>", '<script>return 1;</script></body>'))).toContainEqual(expect.objectContaining({ id: "javascript-syntax" }));
  });
  test("checks attributed script blocks and inline handlers", async () => {
    expect(await failures(deck().replace("</body>", '<script nonce="x">const broken = ;</script></body>'))).toContainEqual(expect.objectContaining({ id: "javascript-syntax" }));
    expect(await failures(deck().replace("</body>", '<div onclick="const broken = ;"></div></body>'))).toContainEqual(expect.objectContaining({ id: "javascript-syntax" }));
  });
});

const mathSource = template.slice(template.indexOf("  function escapeHtml("), template.indexOf("  const graphemeSegmenter"));
const renderMath = new Function(`${mathSource}\nreturn renderMathAware;`)() as (text: string) => string;
describe("VIS-06 finite offline math", () => {
  test.each([
    ["$x^2+y$", "x<sup>2</sup>+y"],
    ["$x_1a$", "x<sub>1</sub>a"],
    ["$x^2-y$", "x<sup>2</sup>-y"],
    ["$x^{2+y}$", "x<sup>2+y</sup>"],
    ["$x_{12}a$", "x<sub>12</sub>a"],
    ["$x^\\alpha+y$", "x<sup>α</sup>+y"],
    ["$x^{a_1}$", "x<sup>a<sub>1</sub></sup>"],
    ["$$C(Q)=C_1 \\cdot Q^{-b}$$", "C(Q)=C<sub>1</sub> · Q<sup>-b</sup>"],
  ])("preserves token boundaries: %s", (input, body) => expect(renderMath(input)).toBe(`<span class="math math-display">${body}</span>`));
  test.each(["$\\alphabet$", "$\\timescale$", "$x^$", "$x^{a$", "$\\frac{a}{b}$", "$x^^2$", "$x^2^3$", "$x^{a}b}$"])("keeps unsupported or malformed source intact: %s", input => expect(renderMath(input)).toBe(input));
  test("unknown command falls back for the entire expression, not a changed prefix", () => expect(renderMath("before $x^2+\\alphabet$ after")).toBe("before $x^2+\\alphabet$ after"));
  test("keeps prices and escapes raw unsupported markup", () => {
    expect(renderMath("$20/month")).toBe("$20/month");
    expect(renderMath("$\\unknown<>&$")).toBe("$\\unknown&lt;&gt;&amp;$");
  });
});
