import { parse, type Expression, type MemberExpression } from "acorn";
import { simple } from "acorn-walk";
import { decodeHTMLAttribute } from "entities";

// Bun supplies real tags/raw-text blocks. Attribute entities follow HTML's attribute
// rules; script/style raw text must NOT be entity-decoded.
export async function inspectMarkup(html: string) {
  const scripts: { text: string; type: string }[] = [];
  const styles: { text: string }[] = [];
  const handlers: string[] = [];
  const resources: string[] = [];
  let current: { text: string; type: string } | undefined;
  let css: { text: string } | undefined;
  await new HTMLRewriter().on("*", {
    element(element) {
      const tag = element.tagName.toLowerCase();
      const attrs = new Map([...element.attributes].map(([name, value]) => [name.toLowerCase(), decodeHTMLAttribute(value)]));
      if (tag === "script") {
        current = { text: "", type: (attrs.get("type") || "").toLowerCase().trim() };
        scripts.push(current);
      }
      if (tag === "style") { css = { text: "" }; styles.push(css); }
      if (attrs.has("style")) styles.push({ text: attrs.get("style")! });
      for (const [name, value] of attrs) {
        if (name.startsWith("on")) handlers.push(value);
        if (["src", "srcset", "poster", "background", "srcdoc"].includes(name)
          || (tag === "object" && name === "data")
          || (["link", "base", "image", "use", "script", "feimage"].includes(tag) && ["href", "xlink:href"].includes(name))) {
          resources.push(`${tag}[${name}]=${value}`);
        }
      }
      if (["iframe", "embed", "object"].includes(tag)) resources.push(tag);
      if (tag === "meta" && attrs.get("http-equiv")?.toLowerCase() === "refresh") resources.push("meta refresh");
    },
  }).on("script", {
    text(chunk) { if (current) current.text += chunk.text; },
  }).on("style", {
    text(chunk) { if (css) css.text += chunk.text; },
  }).transform(new Response(html)).text();
  return { scripts, styles: styles.map(block => block.text), handlers, resources };
}

// Strings/comments cannot declare CSS motion or resources. Escape sequences outside strings
// are decoded so e.g. u\72l(...) is checked too. This only inspects declaration/token syntax.
export function cssCode(source: string) {
  return source.replace(/\/\*[\s\S]*?\*\/|"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'/g, token => token.startsWith("/*") ? " " : '""')
    .replace(/\\([0-9a-f]{1,6})\s?|\\([^\r\n])/gi, (_, hex, char) => hex ? String.fromCodePoint(Math.min(parseInt(hex, 16), 0x10ffff)) : char);
}

function propertyName(node: MemberExpression) {
  if (!node.computed && node.property.type === "Identifier") return node.property.name;
  return node.computed && node.property.type === "Literal" && typeof node.property.value === "string" ? node.property.value : undefined;
}
function callableName(node: Expression | { type: "Super" }): string | undefined {
  if (node.type === "Identifier") return node.name;
  if (node.type === "MemberExpression") return propertyName(node);
  if (node.type === "ChainExpression") return callableName(node.expression);
}

// AST inspection is a static template contract, not arbitrary-program dataflow or a
// sandbox. Calls/imports and executable resource-property writes are inspected; prose,
// strings, comments, regex literals and object-literal data never become calls/sinks.
export function inspectJavaScript(source: string, goal: "script" | "module" | "handler" = "script") {
  const ast = parse(goal === "handler" ? `function handler(event) {\n${source}\n}` : source, {
    ecmaVersion: "latest", sourceType: goal === "module" ? "module" : "script",
  });
  const motion: string[] = [];
  const resources: string[] = [];
  const resourceProperties: Record<string, string[]> = {
    img: ["src", "srcset"], script: ["src"], iframe: ["src", "srcdoc"],
    audio: ["src"], video: ["src", "poster"], source: ["src", "srcset"],
    track: ["src"], embed: ["src"], input: ["src"], body: ["background"],
    link: ["href"], object: ["data"],
  };
  const resourceCalls = new Set(["fetch", "XMLHttpRequest", "WebSocket", "Worker", "EventSource"]);
  // Only unambiguous variable initializers and direct DOM construction/access are
  // recognized. No inferred receivers from property names, arbitrary calls or strings.
  const initializers = new Map<string, Expression | null>();
  simple(ast, {
    VariableDeclarator(node) {
      if (node.id.type === "Identifier") initializers.set(node.id.name,
        initializers.has(node.id.name) ? null : node.init ?? null);
    },
  });
  function receiver(node: Expression | { type: "Super" }, depth = 0): string | undefined {
    if (depth > 8) return;
    if (node.type === "Identifier") {
      if (node.name === "document" && !initializers.has(node.name)) return "document";
      const init = initializers.get(node.name);
      return init ? receiver(init, depth + 1) : undefined;
    }
    if (node.type === "NewExpression") {
      const name = callableName(node.callee);
      if (name === "Image") return "img";
      if (name === "Audio") return "audio";
    }
    if (node.type === "MemberExpression") {
      const parent = receiver(node.object, depth + 1);
      const name = propertyName(node);
      if (parent === "document" && ["body", "head", "documentElement"].includes(name || "")) return name;
      if (parent && !["document", "style"].includes(parent) && name === "style") return "style";
    }
    if (node.type === "CallExpression" && node.callee.type === "MemberExpression") {
      const parent = receiver(node.callee.object, depth + 1);
      const name = propertyName(node.callee);
      if (parent === "document" && ["createElement", "createElementNS"].includes(name || "")) {
        const tag = node.arguments[name === "createElementNS" ? 1 : 0];
        return tag?.type === "Literal" && typeof tag.value === "string" ? tag.value.toLowerCase() : "dom";
      }
      if (parent === "document" && ["getElementById", "querySelector"].includes(name || "")) return "dom";
      if (parent && !["document", "style"].includes(parent) && name === "querySelector") return "dom";
    }
  }
  function literalString(node: Expression): string | undefined {
    if (node.type === "Literal" && typeof node.value === "string") return node.value;
    if (node.type === "TemplateLiteral" && !node.expressions.length) return node.quasis[0].value.cooked ?? undefined;
  }
  const call = (node: { callee: Expression | { type: "Super" } }) => {
    const name = callableName(node.callee);
    if (name === "setInterval" || (name === "animate" && node.callee.type === "MemberExpression")) motion.push(name);
    if (name && resourceCalls.has(name)) resources.push(name);
  };
  simple(ast, {
    CallExpression: call,
    NewExpression: call,
    ImportExpression(node) { resources.push(`import(${source.slice(node.source.start, node.source.end)})`); },
    ImportDeclaration(node) { resources.push(String(node.source.value)); },
    ExportNamedDeclaration(node) { if (node.source) resources.push(String(node.source.value)); },
    ExportAllDeclaration(node) { resources.push(String(node.source.value)); },
    AssignmentExpression(node) {
      if (node.left.type !== "MemberExpression") return;
      const name = propertyName(node.left);
      const target = receiver(node.left.object);
      const allowed = target === "dom" ? Object.values(resourceProperties).flat() : resourceProperties[target || ""] || [];
      if (name && allowed.includes(name)) resources.push(`DOM write .${name}`);
      if (target === "style") {
        const value = literalString(node.right);
        if (value !== undefined && /@import\b|\burl\s*\(|\b(?:-webkit-)?image-set\s*\(/i.test(cssCode(value))) resources.push(`CSS write .${name}`);
      }
    },
  });
  return { motion, resources };
}
