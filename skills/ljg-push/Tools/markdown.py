"""Pure, bounded Org -> Markdown release transformation.

Keys are skill-relative paths; values are (Git mode, bytes). Only explicit output
contracts/templates and resolved references change. Code and input examples are
not output templates. Unsupported Org constructs fail closed.
"""
import json
import posixpath
import re
from pathlib import PurePosixPath


RUNTIME_SUFFIXES = {".ts", ".tsx", ".js", ".mjs", ".cjs", ".json", ".toml", ".yaml", ".yml", ".sh", ".py"}
FORMAT_NEUTRAL = {"fix-ljg-org-to-md"}
HEADER = re.compile(r"^#\+([A-Za-z_]+):[ \t]*(.*)$", re.IGNORECASE)
BLOCK = re.compile(r"^[ \t]*#\+begin_([a-z_]+)(?:[ \t]+(.*))?$", re.IGNORECASE)
FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})([^\r\n]*)$")
INPUT_CONTEXT = re.compile(r"输入示例|输入样例|输入[：:]|原始输入|反例|测试夹具|测试代码|测试字符串|单元测试|夹具|历史|转换前|"
                           r"(?:^|\n)#{1,6}\s*(?:输入|测试)(?:\s|$)|"
                           r"\b(?:input|fixture|test|source example|before conversion)\b", re.IGNORECASE)
OUTPUT_CONTEXT = re.compile(r"输出|模板|文件头|文件结构|最小结构|格式|语法|保存|写入|写笔记|存档|整合为|成品|严格写成|强调|bullet|ASCII|图|迁移行必须|只保留最能闭环|\b(?:output|template|format)\b", re.IGNORECASE)

# Whole instructions, not global Org/Markdown substitutions. Keep accepted input
# formats and examples of the converter itself out of this vocabulary.
INSTRUCTIONS = (
    ("输出必须是纯 org-mode 语法，禁止任何 markdown 语法", "输出必须是纯 Markdown 语法，不混用 Org 语法"),
    ("org-mode 格式，禁止 markdown 语法", "Markdown 格式，不混用 Org 语法"),
    ("格式：org-mode（`*bold*`，禁 markdown 语法）", "格式：Markdown（`**bold**`，不混用 Org 语法）"),
    ("文件必须是 org-mode，禁止 Markdown", "文件必须是 Markdown，不混用 Org 语法"),
    ("org 严格语法（禁混 markdown）", "Markdown 严格语法（不混用 Org）"),
    ("标题用 `*` / `**` / `***`，不要 `#`", "标题用 `#` / `##` / `###`，不要 Org 星号标题"),
    ("加粗 `*字*`，斜体 `/字/`，等宽 `~code~`", "加粗 `**字**`，斜体 `*字*`，等宽 `code`"),
    ("列表用 `-`，不要 `*`（`*` 在 org 是标题）", "列表用 `- item`"),
    ("链接 `[[url][text]]`，不要 `[text](url)`", "链接用 `[text](url)`"),
    ("分隔线 `-----`，不要 `---`；不要 markdown 的 `>` 引用", "分隔线用 `---`；引用用 `>`"),
    ("加粗用 `*bold*`（org-mode），不用 `**bold**`（markdown）", "加粗用 `**bold**`（Markdown）"),
    ("加粗用 `*bold*`（单星号），禁止 `**bold**`", "加粗用 `**bold**`（双星号）"),
    ("分隔线用空行或 org 标题层级区分，不用 `---`（markdown 分隔符）", "分隔用空行或 Markdown 标题层级；分隔线可用 `---`"),
    ("列表用 `- item` 或 `1. item`，不用 markdown 的 `* item`（因为 `*` 在 org 中是标题）", "列表用 `- item` 或 `1. item`"),
    ("列表用 `- item`，不用 `* item`（`*` 在 org 是标题）", "列表用 `- item`"),
    ("分隔用空行或层级，不用 `---`", "分隔用空行或 Markdown 标题层级"),
    ("代码用 `~code~` 或 `=code=`，不用反引号", "行内代码用反引号，代码块用围栏"),
    ("标题层级从 `*` 开始", "标题层级从 `#` 开始"),
    ("Org 加粗使用单星号，标题从 `*` 开始且不跳级。", "Markdown 加粗使用双星号，标题从 `#` 开始且不跳级。"),
    ("Defaults to a saved org note", "Defaults to a saved markdown note"),
    ("Defaults to a saved Org note", "Defaults to a saved Markdown note"),
    ("Produces natural, content-led Org notes", "Produces natural, content-led Markdown notes"),
    ("保存 org 笔记", "保存 Markdown 笔记"), ("保存 Org 笔记", "保存 Markdown 笔记"),
    ("保存为经过验证的 Org 笔记", "保存为经过验证的 Markdown 笔记"),
    ("保存为经校验的 Org 笔记", "保存为经校验的 Markdown 笔记"),
    ("生成由论文内容命名的 Org 笔记", "生成由论文内容命名的 Markdown 笔记"),
    ("写 org 文件时", "写 Markdown 文件时"), ("写 Org 文件时", "写 Markdown 文件时"),
    ("写入 Org 后运行", "写入 Markdown 后运行"),
    ("写入 Org 文件", "写入 Markdown 文件"), ("写入 org 文件", "写入 Markdown 文件"),
    ("写进 org 文件", "写进 Markdown 文件"),
    ("保存为 org 文件", "保存为 Markdown 文件"),
    ("写入 notes 里的 org 文件", "写入 notes 里的 Markdown 文件"),
    ("生成 Org 文件", "生成 Markdown 文件"),
    ("存入 org 笔记", "存入 Markdown 笔记"),
    ("写成 org 笔记", "写成 Markdown 笔记"),
    ("嵌入 ASCII 图（`#+begin_example` 块）", "嵌入 ASCII 图（Markdown 围栏代码块）"),
    ("整合为 org-mode", "整合为 Markdown"), ("格式：org-mode", "格式：Markdown"),
    ("Org-mode 语法", "Markdown 语法"),
    ("Produces org-mode output", "Produces Markdown output"),
    ("生成 org-mode 报告", "生成 Markdown 报告"), ("输出 org-mode", "输出 Markdown"),
    ("org-mode 输出到", "Markdown 输出到"),
    ("Org 文件头", "Markdown 文件头"), ("Org 文件结构", "Markdown 文件结构"),
    ("org 文件结构", "Markdown 文件结构"), ("Org 与 Denote 契约", "Markdown 与 Denote 契约"),
    ("检查字数、Org 标题", "检查字数、Markdown 标题"),
    ("Org 的 `#+begin_example` / `#+end_example`", "Markdown 围栏代码块"),
    ("Org 的 #+begin_example / #+end_example", "Markdown 围栏代码块"),
    ("org 的 `#+begin_example` / `#+end_example` 块", "Markdown 围栏代码块"),
    ("Org example 块", "Markdown 围栏代码块"),
    ("验证 Denote 接受与 `org-lint`", "验证 Denote 接受"),
    ("再运行 Denote 接受检查和 `org-lint`", "再运行 Denote 接受检查"),
    ("Org 笔记中先保存完整分析", "Markdown 笔记中先保存完整分析"),
    ("模板的 `#+schema: ljg-is-v2`", "模板的 `schema: ljg-is-v2`"),
)


def _json(value):
    # JSON strings/arrays are a portable subset of YAML. Never interpolate an Org
    # scalar as YAML: colons, comments, booleans, dates and braces have semantics.
    return json.dumps(value, ensure_ascii=False)


def _code(text):
    runs = re.findall(r"`+", text)
    fence = "`" * max([1, *(len(run) + 1 for run in runs)])
    padding = " " if text.startswith(("`", " ")) or text.endswith(("`", " ")) else ""
    return fence + padding + text + padding + fence


def _emphasis(text):
    text = re.sub(r"(?<![\w*])\*([^*\s](?:[^*\n]*[^*\s])?)\*(?![\w*])", r"**\1**", text)
    return re.sub(r"(?<![\w/:])/([^/\s](?:[^/\n]*[^/\s])?)/(?=[\s.,;:!?，。；：！？]|$)", r"*\1*", text)


INLINE_TOKEN = re.compile(
    r"(?P<ticks>`+)(?P<literal>[^\n]*?)(?P=ticks)|"
    r"(?<!\w)(?P<orgcode>[~=])(?P<code>[^\n]+?)(?P=orgcode)(?!\w)|"
    r"\[\[(?P<target>[^\]\n]+)\](?:\[(?P<label>[^\]\n]+)\])?\]|"
    r"(?P<url>https?://[^\s<>\[\]\"`]+)"
)


def _inline(text):
    # One left-to-right pass: a complete URL/link/code span wins before any
    # delimiters inside it. Process only unprotected gaps and link labels as
    # prose. No sentinel strings means nested protection cannot leak NUL tokens.
    output = []
    offset = 0
    for match in INLINE_TOKEN.finditer(text):
        output.append(_emphasis(text[offset:match.start()]))
        if match['ticks'] or match['url']:
            output.append(match[0])
        elif match['orgcode']:
            output.append(_code(match['code']))
        elif match['label'] is not None:
            output.append('[' + _inline(match['label']) + '](' + match['target'].removeprefix('file:') + ')')
        elif match['target'].startswith('file:'):
            output.append('![](' + match['target'][5:] + ')')
        elif match['target'].startswith(('https://', 'http://')):
            output.append('<' + match['target'] + '>')
        else:
            raise ValueError('Unsupported Org link: ' + match[0])
        offset = match.end()
    output.append(_emphasis(text[offset:]))
    return ''.join(output)


def _org_body(lines):
    output = []
    i = 0
    while i < len(lines):
        line = lines[i]
        block = BLOCK.match(line)
        if block:
            kind, args = block.groups()
            kind = kind.lower()
            if kind not in {"src", "example", "quote"}:
                raise ValueError("Unsupported Org block: " + kind)
            end = re.compile(r"^[ \t]*#\+end_" + kind + r"[ \t]*$", re.IGNORECASE)
            j = i + 1
            depth = 1
            while j < len(lines):
                nested = BLOCK.match(lines[j])
                if kind == "quote" and nested and nested[1].lower() in {"src", "example"}:
                    # Quote delimiters in literal code belong to that code, not
                    # this enclosing quote. Skip the bounded literal block first.
                    literal_kind = nested[1].lower()
                    literal_end = re.compile(r"^[ \t]*#\+end_" + literal_kind + r"[ \t]*$", re.IGNORECASE)
                    j += 1
                    while j < len(lines) and not literal_end.match(lines[j]):
                        j += 1
                    if j == len(lines):
                        raise ValueError("Unclosed Org block: " + literal_kind)
                    j += 1
                    continue
                if kind == "quote" and nested and nested[1].lower() == kind:
                    depth += 1
                if end.match(lines[j]):
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if depth:
                raise ValueError("Unclosed Org block: " + kind)
            inner = lines[i + 1:j]
            if kind == "quote":
                output.extend(">" + (" " + value if value else "") for value in _org_body(inner))
            else:
                language = (args or "").split()[0] if kind == "src" and args else "text"
                if not re.fullmatch(r"[\w+.-]+", language):
                    raise ValueError("Unsupported Org source language: " + language)
                fence = "`" * max([3, *(len(run) + 1 for value in inner for run in re.findall(r"`+", value))])
                output.extend([fence + language, *inner, fence])
            i = j + 1
            continue
        if re.match(r"^[ \t]*#\+end_", line, re.IGNORECASE):
            raise ValueError("Unexpected Org block end: " + line)
        if line.startswith("# "):
            output.append("<!-- " + line[2:] + " -->")
        elif re.match(r"^#\+ATTR_", line, re.IGNORECASE):
            # Presentation hints have no Markdown equivalent; never strip them
            # from src/example payloads (handled before reaching here).
            pass
        elif line.startswith("#+"):
            raise ValueError("Unsupported Org directive: " + line)
        else:
            heading = re.match(r"^(\*+) (.*)$", line)
            if heading:
                if len(heading[1]) > 6:
                    raise ValueError("Markdown supports at most six heading levels")
                line = "#" * len(heading[1]) + " " + heading[2]
            output.append(_inline(line))
        i += 1
    return output


def org_to_md(text):
    """Convert an Org output document, preserving src/example payloads literally."""
    lines = text.splitlines()
    metadata = []
    seen = set()
    i = 0
    while i < len(lines):
        match = HEADER.match(lines[i])
        if not match:
            break
        key, value = match.groups()
        key = key.lower()
        key = "tags" if key == "filetags" else key
        if key in seen:
            raise ValueError("Duplicate Org metadata: " + key)
        seen.add(key)
        if key == "tags":
            value = [tag for tag in value.split(":") if tag.strip()]
        elif key == "date" and value.startswith("[") and value.endswith("]"):
            value = value[1:-1]
        # This deliberately narrow plain scalar is unambiguously a YAML string;
        # retain the documented schema spelling used by both template consumers.
        encoded = value if key == "schema" and re.fullmatch(r"[a-z]+(?:-[a-z0-9]+)+", value) else _json(value)
        metadata.append(key + ": " + encoded)
        i += 1
    output = (["---", *metadata, "---"] if metadata else []) + _org_body(lines[i:])
    return "\n".join(output) + "\n"


def _reference(token, consumer, renames):
    """Only resolve a whole local path from this consumer, never a basename hit."""
    if not token.endswith(".org") or re.search(r"[\x00-\x1f]", token) or token.startswith(("/", "~")) or ":" in token:
        return token
    target = posixpath.normpath(posixpath.join(posixpath.dirname(consumer), token))
    return token[:-4] + ".md" if target in renames else token


def _references(text, consumer, renames):
    # Quoted literals and Markdown destinations. A fixture containing prose or an
    # Org document is not a path; paths with .bak or longer basenames do not match.
    text = re.sub(r"([\"'`])([^\n\"'`]+)\1", lambda m: m[1] + _reference(m[2], consumer, renames) + m[1], text)
    return re.sub(r"(?<=\]\()([^\s()]+)(?=\))", lambda m: _reference(m[0], consumer, renames), text)


def _note_path(path):
    return "://" not in path and bool(re.search(
        r"__(?:qa|paper|think|concept|rank|structure|is|write|constraint|plain|blind|book|reading|relationship|roundtable)\.org$", path)
        or re.search(r"--投资分析-[^/]+\.org$", path))


def _output_paths(line):
    return re.sub(r"`([^`\n]+\.org)`", lambda m: "`" + m[1][:-4] + ".md`" if _note_path(m[1]) else m[0], line)


def _instruction(line, context):
    if INPUT_CONTEXT.search(line):
        return line
    if INPUT_CONTEXT.search(context) and not OUTPUT_CONTEXT.search(context):
        return line
    # Pure input explanations are not changed just because they mention Org.
    if re.search(r"接受|输入|fixture|测试", line, re.IGNORECASE) and not re.search(r"保存|写入|输出|文件名", line):
        return line
    for old, new in INSTRUCTIONS:
        line = line.replace(old, new)
    if re.search(r"补|frontmatter|文件|写完|检索|source.*参考资料|是否在正文完成后|只有一个裸 URL|能回答.*以后怎样判断", line):
        line = re.sub(r"(?<=`)#\+(DESCRIPTION|description|source)(?=`)", lambda m: m[1].lower(), line)
    line = _output_paths(line)
    # Compatibility with compact skill format declarations, not free-standing
    # mentions of Org in prose or arbitrary code.
    line = re.sub(r"\bin org-mode(?=\s*$)", "in markdown", line)
    return line


def _output_block(language, payload, context):
    if language.lower() not in {"", "org"} or INPUT_CONTEXT.search(context):
        return False
    # The QA contract uses four emphasized paragraphs, not Org headings. Require
    # both its explicit four-part context and all four ordered labels so arbitrary
    # Markdown italics in an unlabeled fence remain untouched.
    if re.search(r"每个 A 严格四段|A 的四段", context):
        labels = re.findall(r"^\*(结论|形式化|怎么想到的|边界)\*：", payload, re.MULTILINE)
        if labels == ["结论", "形式化", "怎么想到的", "边界"]:
            return True
    return bool(OUTPUT_CONTEXT.search(context) and re.search(r"^(?:#\+|\*+ |\s*- \*[^*\n]+\*：)", payload, re.MULTILINE))


def _audit_instruction(line, path):
    # Audit only active prose, never accepted-input descriptions or code payloads.
    if re.search(r"(?:保存为?|写入|写成|存入|生成)[^\n。]{0,24}(?:org-mode|Org 文件|org 文件|Org 笔记|org 笔记)|"
                 r"(?:输出|格式|语法)[^\n。]{0,16}org-mode|"
                 r"[Mm]arkdown[^\n。]{0,16}(?:禁止|禁)[^\n。]*[Mm]arkdown", line):
        raise ValueError("Markdown conversion residual: " + path)


def _quoted_line(line):
    match = re.match(r"^( {0,3}(?:>[ \t]?)+)(.*)$", line.rstrip("\r\n"))
    return (match[1].count(">"), match[2]) if match else (0, line.rstrip("\r\n"))


def _markdown(text, path, renames, literal_fences=False):
    lines = text.splitlines(keepends=True)
    output = []
    recent = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Preserve four-column/tab-indented literal code. Ambiguous list
        # continuations are deliberately left alone rather than treated as
        # active output instructions; no full CommonMark block parser is needed.
        if line.expandtabs(4).startswith("    "):
            output.append(line)
            i += 1
            continue
        quote_depth, quote_content = _quoted_line(line)
        quoted_fence = FENCE.match(quote_content) if quote_depth else None
        if quoted_fence:
            marker = quoted_fence[2]
            closing = re.compile(r"^ {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*$")
            j = i + 1
            while j < len(lines):
                depth, content = _quoted_line(lines[j])
                if depth < quote_depth:
                    break  # The quote container ended; do not consume prose after it.
                if depth == quote_depth and closing.match(content):
                    j += 1
                    break
                j += 1
            output.extend(lines[i:j])
            i = j
            continue
        opening = FENCE.match(line.rstrip("\r\n"))
        if opening:
            indent, marker, info = opening.groups()
            closing = re.compile(r"^ {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*$")
            j = i + 1
            while j < len(lines) and not closing.match(lines[j].rstrip("\r\n")):
                j += 1
            if j == len(lines):
                raise ValueError("Unclosed Markdown fence: " + path)
            body = "".join(lines[i + 1:j])
            payload = "".join(value[len(indent):] if value.startswith(indent) else value for value in lines[i + 1:j])
            context = "\n".join(recent[-4:])
            if not literal_fences and _output_block(info.strip(), payload, context):
                converted = org_to_md(payload)
                # The outer template fence must not be closed by a generated code
                # fence within its payload.
                outer = marker[0] * max([len(marker), *(len(run) + 1 for run in re.findall(re.escape(marker[0]) + r"+", converted))])
                output.append(indent + outer + "markdown\n")
                output.extend(indent + value + "\n" for value in converted.splitlines())
                output.append(indent + outer + "\n")
            else:
                # Existing Markdown/code/input examples stay byte-identical. Only
                # resolved runtime references and an explicit validator CLI operand
                # may change inside executable command examples.
                if not literal_fences and info.strip().lower() in {"sh", "bash", "shell"}:
                    body = _references(body, path, renames)
                    if "validate_note" in body or "ValidateNote" in body:
                        body = re.sub(r"[^\s\"']+\.org(?=[\s\"']|$)",
                                      lambda m: m[0][:-4] + ".md" if _note_path(m[0]) or m[0].endswith("/note.org") else m[0], body)
                # A user/assistant invocation transcript is an explicit output
                # contract, not executable code or a generic text literal.
                if not literal_fences and not info.strip() and payload.lstrip().startswith("User:"):
                    body = "".join(_instruction(value, "输出示例") for value in body.splitlines(keepends=True))
                output.extend([line, body, lines[j]])
            i = j + 1
            continue
        stripped = line.strip()
        context = "\n".join(recent[-4:])
        converted_line = _references(_instruction(line, context), path, renames)
        if "技能根目录" in converted_line:
            root_consumer = PurePosixPath(path).parts[0] + "/SKILL.md"
            converted_line = re.sub(r"(技能根目录[^`\n]*`)([^`\n]+)(`)",
                                    lambda m: m[1] + _reference(m[2], root_consumer, renames) + m[3], converted_line)
        if not INPUT_CONTEXT.search(context) and not INPUT_CONTEXT.search(line):
            _audit_instruction(converted_line, path)
        output.append(converted_line)
        if stripped:
            if re.match(r"^#{1,6} ", stripped):
                recent = [stripped]
            else:
                recent.append(stripped)
        i += 1
    return "".join(output)


def mdize(tree):
    """Return a new {skill-relative path: (Git mode, bytes)}; never write an input."""
    result = dict(tree)
    renames = {}
    for path in sorted(tree):
        p = PurePosixPath(path)
        if p.parts[0] in FORMAT_NEUTRAL or "assets" in p.parts or p.suffix != ".org":
            continue
        dest = str(p.with_suffix(".md"))
        if dest in tree:
            raise ValueError("Org/Markdown output collision: " + dest)
        renames[path] = dest
    for source, dest in renames.items():
        mode, data = result.pop(source)
        # Generated Org templates are already structurally converted. Do not then
        # parse their fenced literals as skill instructions a second time.
        text = org_to_md(data.decode("utf-8"))
        text = _markdown(text, dest, renames, literal_fences=True)
        result[dest] = (mode, text.encode("utf-8"))
    for path, (mode, data) in list(result.items()):
        p = PurePosixPath(path)
        if path in renames.values() or p.parts[0] in FORMAT_NEUTRAL or "assets" in p.parts:
            continue
        if p.suffix == ".md":
            text = _markdown(data.decode("utf-8"), path, renames)
        elif p.suffix in RUNTIME_SUFFIXES:
            text = _references(data.decode("utf-8"), path, renames)
        else:
            continue
        result[path] = (mode, text.encode("utf-8"))
    return result
