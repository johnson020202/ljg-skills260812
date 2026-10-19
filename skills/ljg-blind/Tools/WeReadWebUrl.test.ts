import { expect, test } from "bun:test";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createWeReadWebUrl } from "./WeReadWebUrl";

const documentedUrl = "https://weread.qq.com/web/reader/b2632d7058c218b269e80c0kc51323901dc51ce410c121b";

test("retains the documented offline chapter URL vector", () => {
  expect(createWeReadWebUrl("573976", "13")).toBe(documentedUrl);
});

test("TXT-08 documented book and chapter commands use the loaded project skill", () => {
  const skill = readFileSync(new URL("../SKILL.md", import.meta.url), "utf8");
  const commands = skill.split("\n").filter((line) => line.startsWith("bun ") && line.includes("WeReadWebUrl.ts"));
  expect(commands.length).toBe(2);
  const root = mkdtempSync(join(tmpdir(), "blind project install "));
  try {
    const skillDir = join(root, ".agents/skills/ljg-blind");
    const home = join(root, "empty-home");
    mkdirSync(join(skillDir, "Tools"), { recursive: true });
    mkdirSync(home);
    copyFileSync(new URL("./WeReadWebUrl.ts", import.meta.url), join(skillDir, "Tools/WeReadWebUrl.ts"));
    for (const command of commands) {
      expect(command).toContain('"{skill_dir}/Tools/WeReadWebUrl.ts"');
      const resolved = command.replace("{skill_dir}", skillDir).replace("<bookId>", "573976").replace("<chapterUid>", "13");
      const result = Bun.spawnSync(["/bin/sh", "-c", resolved], { cwd: root, env: { ...process.env, HOME: home } });
      expect(result.exitCode).toBe(0);
      expect(result.stdout.toString().trim()).toBe(command.includes("<chapterUid>") ? documentedUrl : createWeReadWebUrl("573976"));
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});
