"""Only synthetic JSONL under TemporaryDirectory; never reads the user's history."""
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

TOOLS = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("blind_extract", TOOLS / "extract_conversations.py")
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)


def message(timestamp, content, **fields):
    return {"type": "user", "timestamp": timestamp,
            "message": {"role": "user", "content": content}, **fields}


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="blind-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "projects"
        self.root.mkdir()
        self.zone = ZoneInfo("Asia/Shanghai")

    def write(self, records, path="-Users-auditor-project/session.jsonl"):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
        return target

    def extract(self, target="2026-10-18"):
        return extractor.extract_conversations(self.root, target, self.zone)

    def test_other_user_project_and_string_or_text_blocks(self):
        self.write([message("2026-10-18T12:00:00Z", "真人输入。"),
                    message("2026-10-18T12:01:00Z", [{"type": "text", "text": "第一行"}, {"type": "text", "text": "第二行"}])])
        result = self.extract()
        self.assertEqual(result["message_count"], 2)
        self.assertEqual(result["messages"][1]["text"], "第一行\n第二行")
        self.assertEqual(result["status"], "sparse")
        self.assertTrue(result["messages"][0]["timestamp"].endswith("+08:00"))

    def test_local_interval_includes_start_excludes_end_and_accepts_offsets(self):
        self.write([
            message("2026-10-17T16:00:00Z", "start"),
            message("2026-10-17T16:30:00Z", "凌晨"),
            message("2026-10-18T15:59:59.999Z", "end minus epsilon"),
            message("2026-10-18T16:00:00Z", "next day"),
            message("2026-10-18T00:30:00+08:00", "offset"),
            message("2026-10-18T00:00:00-07:00", "negative offset"),
            message("2026-10-17T15:59:59Z", "too early"),
        ])
        result = self.extract()
        self.assertEqual([m["text"] for m in result["messages"]], ["start", "凌晨", "offset", "negative offset", "end minus epsilon"])
        self.assertEqual(result["interval"], {"start": "2026-10-18T00:00:00+08:00", "end": "2026-10-19T00:00:00+08:00"})

    def test_dst_days_have_local_midnight_boundaries(self):
        zone = ZoneInfo("America/New_York")
        for target, hours in [("2026-03-08", 23), ("2026-11-01", 25)]:
            with self.subTest(target=target):
                start, end = extractor.day_interval(target, zone)
                delta = end.astimezone(dt.timezone.utc) - start.astimezone(dt.timezone.utc)
                self.assertEqual(delta.total_seconds() / 3600, hours)

    def test_all_noise_is_empty_not_error_or_original_text(self):
        self.write([message("2026-10-18T12:00:00Z", "<system-reminder>\n系统噪声\n</system-reminder>"),
                    message("2026-10-18T12:01:00Z", "<local-command-caveat>\n正文\n</local-command-caveat>"),
                    message("2026-10-18T12:02:00Z", "/ljg-blind 2026-10-18")])
        result = self.extract()
        self.assertEqual(result["messages"], [])
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["filtered_messages"], 3)
        self.assertEqual(result["text_chars"], 0)

    def test_filters_whole_message_not_individual_lines(self):
        self.write([message("2026-10-18T12:00:00Z", [{"type": "text", "text": "<system-reminder>\n系统噪声\n</system-reminder>"},
                                                       {"type": "text", "text": "同条注入续文"}])])
        self.assertEqual(self.extract()["messages"], [])

    def test_compaction_summary_is_not_human_even_when_long_enough(self):
        self.write([message("2026-10-18T12:00:00Z", "自动摘要" * 90, isCompactSummary=True)])
        result = self.extract()
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["messages"], [])
        self.assertEqual(result["filtered_messages"], 1)

    def test_transcript_only_continuation_is_not_human(self):
        self.write([message("2026-10-18T12:00:00Z", "合成续接" * 90, isVisibleInTranscriptOnly=True)])
        result = self.extract()
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["messages"], [])
        self.assertEqual(result["filtered_messages"], 1)

    def test_noise_tag_examples_in_fenced_code_are_human_text(self):
        for text in [
            "请解释下面这个标签是否会被误删？\n```xml\n<system-reminder>示例，不是系统消息</system-reminder>\n```",
            "~~~xml\n<system-reminder>示例</system-reminder>\n~~~\n这段是什么意思？",
            "````text\n```xml\n<task-notification>示例</task-notification>\n```\n````",
        ]:
            with self.subTest(text=text):
                self.write([message("2026-10-18T12:00:00Z", text)])
                self.assertEqual([m["text"] for m in self.extract()["messages"]], [text])

    def test_noise_tags_quoted_or_discussed_inside_a_question_are_not_outer_wrappers(self):
        for text in [
            "> <system-reminder>引用\n> 引用的正文\n> </system-reminder>\n这是什么意思？",
            "`<system-reminder>` 是什么？",
            "请解释下面这个 XML：\n<system-reminder>这是例子</system-reminder>",
            "<system-reminder-example>不同的标签</system-reminder-example>",
        ]:
            with self.subTest(text=text):
                self.write([message("2026-10-18T12:00:00Z", text)])
                self.assertEqual([m["text"] for m in self.extract()["messages"]], [text])

    def test_metadata_still_filters_synthetic_text_that_looks_like_a_question(self):
        text = "请解释下面的示例：\n```xml\n<system-reminder>示例</system-reminder>\n```"
        self.write([message("2026-10-18T12:00:00Z", text, isMeta=True)])
        self.assertEqual(self.extract()["status"], "empty")

    def test_role_source_flags_and_tool_results_are_not_human(self):
        records = [message("2026-10-18T12:00:00Z", "sidechain", isSidechain=True),
                   message("2026-10-18T12:00:00Z", "meta", isMeta=True),
                   message("2026-10-18T12:00:00Z", "agent", source="subagent"),
                   message("2026-10-18T12:00:00Z", "auto", isSynthetic=True),
                   message("2026-10-18T12:00:00Z", [{"type": "tool_result", "tool_use_id": "fake", "content": "tool output"}, {"type": "text", "text": "tool continuation"}]),
                   {"type": "assistant", "message": {"content": "assistant"}},
                   {"type": "user", "message": {"role": "system", "content": "system"}}]
        self.write(records)
        self.assertEqual(self.extract()["messages"], [])

    def test_subagents_workflows_and_symlinks_are_not_scanned(self):
        self.write([message("2026-10-18T12:00:00Z", "top")])
        for path in ["project/session/subagents/child.jsonl", "project/workflows/child.jsonl", "workflows/child.jsonl", "subagents/child.jsonl"]:
            self.write([message("2026-10-18T12:00:00Z", "not top")], path)
        outside = Path(self.temp.name) / "outside.jsonl"
        outside.write_text("not even JSON", encoding="utf-8")
        (self.root / "-Users-auditor-project/link.jsonl").symlink_to(outside)
        result = self.extract()
        self.assertEqual(result["files_scanned"], 1)
        self.assertEqual([m["text"] for m in result["messages"]], ["top"])

    def test_normal_discussion_of_noise_tokens_is_retained(self):
        text = "请解释 tool_use_id、system-reminder 和 ljg-blind 的用途；不是让你扫盲区。"
        self.write([message("2026-10-18T12:00:00Z", text)])
        self.assertEqual(self.extract()["messages"][0]["text"], text)

    def test_missing_source_is_an_error(self):
        with self.assertRaises(extractor.ExtractionError):
            extractor.extract_conversations(self.root / "missing", "2026-10-18", self.zone)

    def test_no_top_level_session_files_is_an_error(self):
        with self.assertRaises(extractor.ExtractionError):
            self.extract()

    def test_no_supported_session_records_is_an_error(self):
        self.write([{"type": "session_meta", "payload": {"id": "synthetic"}}])
        with self.assertRaises(extractor.ExtractionError):
            self.extract()

    def test_valid_source_with_no_matching_date_is_empty(self):
        self.write([message("2026-10-16T00:00:00Z", "other day")])
        self.assertEqual(self.extract()["status"], "empty")

    def test_sparse_and_adequate_text_status(self):
        for length, status in [(199, "sparse"), (200, "ok")]:
            self.write([message("2026-10-18T12:00:00Z", "字" * length)])
            self.assertEqual(self.extract()["status"], status)

    def test_invalid_timestamp_is_error_not_silent_omission(self):
        for value in [None, "2026-10-18T00:00:00", "nonsense", "2026-02-30T00:00:00Z"]:
            with self.subTest(value=value):
                self.write([message(value, "text")])
                with self.assertRaises(extractor.ExtractionError):
                    self.extract()

    def test_invalid_json_or_schema_is_error(self):
        target = self.write([])
        for text in ["{broken\n", "[]\n", json.dumps({"type": "user", "message": {"content": 12}}), json.dumps({"type": "user"})]:
            with self.subTest(text=text):
                target.write_text(text, encoding="utf-8")
                with self.assertRaises(extractor.ExtractionError):
                    self.extract()

    def test_invalid_date_is_error(self):
        for target in ["2026-2-3", "2026-02-30", "not-a-date"]:
            with self.subTest(target=target), self.assertRaises(extractor.ExtractionError):
                extractor.day_interval(target, self.zone)

    def test_root_resolution_uses_supplied_home_or_config_not_author(self):
        self.assertEqual(extractor.resolve_projects_root(None, {}, Path("/synthetic/home")), Path("/synthetic/home/.claude/projects"))
        self.assertEqual(extractor.resolve_projects_root(None, {"CLAUDE_CONFIG_DIR": "/synthetic/config"}, Path("/synthetic/home")), Path("/synthetic/config/projects"))
        self.assertEqual(extractor.resolve_projects_root("/synthetic/explicit", {}, Path("/synthetic/home")), Path("/synthetic/explicit"))

    def test_cli_project_install_uses_explicit_root_and_timezone(self):
        self.write([message("2026-10-17T16:30:00Z", "午夜输入")])
        installed = Path(self.temp.name) / "project space/.agents/skills/ljg-blind/Tools/extract_conversations.py"
        installed.parent.mkdir(parents=True)
        shutil.copyfile(TOOLS / "extract_conversations.py", installed)
        result = subprocess.run([sys.executable, "-B", str(installed), "--host", "claude-code", "--projects-root", str(self.root), "--date", "2026-10-18", "--timezone", "Asia/Shanghai"], capture_output=True, text=True, env={**os.environ, "HOME": str(Path(self.temp.name) / "empty-home")})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["messages"][0]["timestamp"], "2026-10-18T00:30:00+08:00")

    def test_default_cli_command_uses_synthetic_config_root_and_local_yesterday(self):
        now = dt.datetime.now(ZoneInfo("Pacific/Kiritimati"))
        day = now.date() - dt.timedelta(days=1)
        timestamp = dt.datetime.combine(day, dt.time(12), now.tzinfo).isoformat()
        self.write([message(timestamp, "昨天的合成输入")])
        env = {**os.environ, "HOME": str(Path(self.temp.name) / "empty-home"),
               "CLAUDE_CONFIG_DIR": str(self.root.parent), "TZ": "Pacific/Kiritimati"}
        result = subprocess.run([sys.executable, "-B", str(TOOLS / "extract_conversations.py"), "--host", "claude-code"], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["date"], day.isoformat())
        self.assertEqual(json.loads(result.stdout)["message_count"], 1)

    def test_cli_all_filtered_returns_explicit_empty_success(self):
        self.write([message("2026-10-18T12:00:00Z", "<system-reminder>noise</system-reminder>")])
        result = subprocess.run([sys.executable, "-B", str(TOOLS / "extract_conversations.py"), "--host", "claude-code", "--projects-root", str(self.root), "--date", "2026-10-18", "--timezone", "Asia/Shanghai"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "empty")
        self.assertEqual(json.loads(result.stdout)["messages"], [])

    def test_cli_errors_do_not_emit_partial_conversations(self):
        self.write([message("2026-10-18T12:00:00Z", "private synthetic text")])
        for extra in [["--host", "codex"], ["--host", "claude-code", "--timezone", "Not/AZone"], []]:
            with self.subTest(extra=extra):
                result = subprocess.run([sys.executable, "-B", str(TOOLS / "extract_conversations.py"), "--projects-root", str(self.root), "--date", "2026-10-18", *extra], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("private synthetic text", result.stderr)


if __name__ == "__main__":
    unittest.main()
