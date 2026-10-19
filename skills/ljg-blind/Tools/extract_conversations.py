#!/usr/bin/env python3
"""Local Claude Code JSONL extraction. No network, shell, or output-file writes."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ExtractionError(ValueError):
    """Unavailable, invalid, or unsupported evidence must not look like an empty day."""


# Only an unquoted outer wrapper is evidence of a synthetic message. Never search
# within human prose: fenced code, Markdown quotes and inline examples are data.
NOISE_WRAPPER = re.compile(
    r"\A<(?:system-reminder|task-notification|local-command(?:-[a-z-]+)?|"
    r"command-name|command-message|caveat)(?=[\s>])", re.IGNORECASE,
)
INVOCATION = re.compile(
    r"(?:/?ljg-blind|扫盲区|照盲区|看看我的思维盲区|我昨天想漏了什么)"
    r"(?:\s+\d{4}-\d{2}-\d{2})?[。！!？?]?", re.IGNORECASE,
)


def resolve_projects_root(explicit, env, home):
    if explicit:
        return Path(explicit).expanduser()
    config = env.get("CLAUDE_CONFIG_DIR")
    return (Path(config).expanduser() if config else home / ".claude") / "projects"


def local_timezone(name=None):
    name = name or os.environ.get("TZ")
    try:
        if name:
            return ZoneInfo(name.removeprefix(":"))
        # Use the OS timezone database, not today's fixed UTC offset (DST matters).
        with Path("/etc/localtime").open("rb") as source:
            return ZoneInfo.from_file(source, key="local")
    except (OSError, ValueError, ZoneInfoNotFoundError) as error:
        raise ExtractionError("无法解析本地时区；请用 --timezone 指定有效 IANA 时区") from error


def day_interval(target, timezone):
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", target):
            raise ValueError("date format")
        day = dt.date.fromisoformat(target)
        start = dt.datetime.combine(day, dt.time.min, timezone)
        end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min, timezone)
        return start, end
    except (ValueError, OverflowError) as error:
        raise ExtractionError("日期必须是有效的 YYYY-MM-DD") from error


def parse_timestamp(value):
    if not isinstance(value, str):
        raise ExtractionError("真人消息缺少有效 timestamp")
    try:
        timestamp = dt.datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timezone missing")
        return timestamp
    except ValueError as error:
        raise ExtractionError("timestamp 必须包含有效的 Z 或 UTC offset，不能猜测无时区时间") from error


def human_text(record):
    if record.get("type") != "user":
        return None
    if any(record.get(flag) for flag in (
        "isMeta", "isSidechain", "isSynthetic", "isCompactSummary",
        "isVisibleInTranscriptOnly", "tool_use_id",
    )):
        return None
    if record.get("source") not in (None, "user", "human"):
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        raise ExtractionError("user 记录缺少 message 对象")
    if message.get("role", "user") != "user":
        return None
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(not isinstance(block, dict) for block in content):
            raise ExtractionError("message.content 数组项必须是对象")
        if any(block.get("type") in ("tool_result", "tool_use") for block in content):
            return None
        blocks = [block.get("text") for block in content if block.get("type") == "text"]
        if any(not isinstance(text, str) for text in blocks):
            raise ExtractionError("text block 缺少文本")
        text = "\n".join(blocks)
    else:
        raise ExtractionError("不支持的 message.content 格式")
    text = text.strip()
    if not text or NOISE_WRAPPER.match(text) or INVOCATION.fullmatch(text):
        return None
    return text


def session_files(root):
    if not root.is_dir():
        raise ExtractionError("会话数据根不可用；请确认宿主及 --projects-root，不可当作当天无对话")
    files = []
    # Exactly projects/<project>/<session>.jsonl; never recurse into agent/workflow logs.
    for project in sorted(root.iterdir()):
        if project.is_symlink() or not project.is_dir() or project.name in ("subagents", "workflows"):
            continue
        files.extend(path for path in sorted(project.glob("*.jsonl")) if path.is_file() and not path.is_symlink())
    if not files:
        raise ExtractionError("数据根没有顶层会话 JSONL；数据源不足，不能推断当天无对话")
    return files


def extract_conversations(root, target, timezone):
    start, end = day_interval(target, timezone)
    start_utc, end_utc = start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)
    messages = []
    recognized = filtered = 0
    try:
        paths = session_files(root)
        for path in paths:
            with path.open(encoding="utf-8-sig") as source:
                for number, line in enumerate(source, 1):
                    if not line.strip():
                        continue
                    location = f"{path.relative_to(root)}:{number}"
                    try:
                        record = json.loads(line)
                        if not isinstance(record, dict):
                            raise ExtractionError("JSONL 记录必须是对象")
                        if record.get("type") in ("user", "assistant", "system"):
                            recognized += 1
                        text = human_text(record)
                        if text is None:
                            if record.get("type") == "user":
                                filtered += 1
                            continue
                        timestamp = parse_timestamp(record.get("timestamp")).astimezone(dt.timezone.utc)
                        if start_utc <= timestamp < end_utc:
                            messages.append((timestamp, {
                                "timestamp": timestamp.astimezone(timezone).isoformat(),
                                "text": text, "source": location,
                            }))
                    except (json.JSONDecodeError, ExtractionError) as error:
                        # Do not echo the original line or any conversation text on failure.
                        detail = "无效 JSON" if isinstance(error, json.JSONDecodeError) else str(error)
                        raise ExtractionError(f"{location}: {detail}") from error
    except (OSError, UnicodeError) as error:
        raise ExtractionError("无法完整读取会话数据；请检查路径、权限或 UTF-8 编码") from error
    if not recognized:
        raise ExtractionError("未找到支持的 Claude Code 消息记录；不支持的宿主/导出格式不能视作无对话")
    ordered = [item for _, item in sorted(messages, key=lambda pair: pair[0])]
    chars = sum(len(re.sub(r"\s", "", item["text"])) for item in ordered)
    return {
        "status": "empty" if not ordered else "sparse" if chars < 200 else "ok",
        "date": target, "timezone": str(timezone),
        "interval": {"start": start.isoformat(), "end": end.isoformat()},
        "files_scanned": len(paths), "filtered_messages": filtered,
        "message_count": len(ordered), "text_chars": chars, "messages": ordered,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="仅本地读取 Claude Code 顶层 JSONL；stdout 输出 JSON，不上传、不写笔记。")
    parser.add_argument("--host", required=True, help="必须明确为 claude-code；其他宿主尚不支持")
    parser.add_argument("--projects-root", help="默认 $CLAUDE_CONFIG_DIR/projects 或 ~/.claude/projects")
    parser.add_argument("--date", help="目标本地日 YYYY-MM-DD，默认昨天")
    parser.add_argument("--timezone", help="IANA 时区；默认 TZ 或系统 /etc/localtime")
    args = parser.parse_args(argv)
    try:
        if args.host != "claude-code":
            raise ExtractionError("不支持此宿主；请提供 Claude Code JSONL 导出或用户主动提供的文本，不自动扫描其他宿主")
        timezone = local_timezone(args.timezone)
        target = args.date or (dt.datetime.now(timezone).date() - dt.timedelta(days=1)).isoformat()
        root = resolve_projects_root(args.projects_root, os.environ, Path.home())
        result = extract_conversations(root, target, timezone)
    except ExtractionError as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
