---
name: ljg-push
description: 安全发布 ljg-* skills 到 johnson020202/ljg-skills260812 的 master 与 md 分支。先只读预检，在临时仓库生成两种输出，最后原子推送。Use when user says '/ljg-push', 'push skills', '推送 skills', '同步 skills', or 'sync ljg'. NOT FOR arbitrary repositories or installation.
user_invocable: true
---

# ljg-push

本地安装源是 master 风格输入；`md` 是确定性生成结果，不是第二个可手工编辑的源。调用前先按 `Workflows/Push.md` 检查范围。依赖 Python 3.9+ 标准库、Git、Bash，无额外包。

## 调用

从**本次实际加载的技能目录**执行，不回退到旧全局副本。

```bash
bash {skill_dir}/Tools/Push.sh --dry-run
bash {skill_dir}/Tools/Push.sh --repo /path/to/ljg-skills260812 --local /path/to/skills
bash {skill_dir}/Tools/Push.sh --skill ljg-qa --skill ljg-paper
```

| 参数 | 默认及语义 |
|------|------------|
| `--repo` / `SKILLS_REPO` | `~/code/ljg-skills260812`，必须已存在，不自动 clone |
| `--local` / `SKILLS_LOCAL` | `~/.agents/skills`，只读安装源 |
| `--origin` / `REPO_URL` | 默认仅接受此 fork 的精确 HTTPS / SSH URL；覆盖值必须与 origin fetch、push URL 完全一致 |
| `--source-branch` / `--md-branch` | `master` / `md`，当前 checkout 必须是 source 分支；脚本不切分支 |
| `--skill` | 可重复，未给出时选择源目录全部 `ljg-*` 及唯一兼容名 `fix-ljg-org-to-md`；不接受任意前缀或路径 |
| `--force` | 兼容旧选项；选择全部本地技能（有 `--skill` 时仍限该列表），不强推、不跳过安全检查、无实际变更不 bump |
| `--dry-run` | 只读本地文件和 Git 对象；不写临时文件或 index、不联网、不提交、不切分支 |
| `--skip-readme-check` | 仅绕过 README 技能名称门禁，不绕过其他检查 |
| `--message` | 提交说明，自动追加集合版本 |

默认身份是 `johnson020202/ljg-skills260812`。例如 `https://github.com/johnson020202/ljg-skills260812.git` 和 `git@github.com:johnson020202/ljg-skills260812.git` 均允许；相似前缀、其他 fork、多 push URL、不同 fetch/push URL 拒绝。显式 origin 可用于已批准的私有镜像。

旧入口 `scripts/sync-push.sh <skill-name> <commit-message> [选项]` 仅包装此发布器，保留 `~/.claude/ljg-skills-repo` / `~/.claude/skills` 默认路径，但也执行双分支安全预检；可用上述选项覆盖路径。

## 安全契约

1. **干净仓库才可发布**：拒绝 staged、unstaged、untracked、未完成 rebase/merge、隐藏变更的 index 标志及重定向 Git 环境。README 和根工具改动应由操作者先正常提交；发布器只读取已提交 source，不夹带工作目录内容。
2. **明确文件清单**：技能名仅允许 `ljg-*` 的受限命名及精确兼容名 `fix-ljg-org-to-md`；源和目标 realpath 必须在指定根目录，拒绝 symlink、submodule、非普通文件和源 hardlink。source 暂存实际变更的技能文件及两份版本 JSON；md 另同步根文件白名单 `README.md`、`CLAUDE.md`、`LICENSE`、`.gitignore`、`scripts/**`、`docs/**`、`.github/**`，包含内容、执行模式及删除。根范围常量为 `ROOT_PATHS`；`.claude-plugin/` 仍仅管理两份元数据。逐项核对 staged 清单和提交回读，不整目录夹带工作树。
3. **安装源需人工审查**：除 `.git`、`node_modules`、`__pycache__`、`.DS_Store`、`.pyc`、`.log` 外，选中技能的普通文件都会纳入。尤其应移走凭据与临时文件；不要把 `.gitignore` 当发布授权。
4. **用户仓库不写入**：构建和本地提交只在 disposable Git 仓库发生。绝不执行 `reset --hard`、checkout、pull、fetch 或 rebase；失败不会改用户 HEAD、index、文件，也不自动重试推送。
5. **版本结构化更新**：先校验 plugin、marketplace 顶层、对应 `plugins[]` 的三处 `major.minor.patch` 一致；只更新这三处。仅 source 技能实际变化才 bump patch，写入后和提交后均核对。只有根工具更新时仍生成 md 提交，但不 bump、不生成额外 source 提交；两者都无变化才是 no-op。不会顺带改其他插件版本或创建 tag。
6. **远端明确且原子**：正式发布先只读 `ls-remote`，要求 remote 分支和本地基线一致；构建成功后，以完整 commit→refs/heads refspec、精确旧 SHA lease，一次 `push --atomic` 发布两分支。提交保持父链，不改写历史。服务端不支持原子 push 就失败，绝不降级为可能半发布的两次 push。
7. **dry-run 不等于发布验证**：它仍拒绝本地不安全状态；README 缺项仅警告，但不会检查远端新旧或凭据。

成功后输入仓库依然保持原样，可能落后远端。操作者应明确 fetch 并 fast-forward 后再发布；脚本不会替你更新或清理。网络中断若结果不确定，应先查询远端 refs 再决定重试，不盲目重推。

## Markdown 来源与迁移

`md` 的整个 `skills/` 必须等于记录的 source 提交经过当前转换器的结果；上述根文件白名单必须逐字节、逐执行模式等于同一个 source 基线，人工补丁不能被静默覆盖。生成提交用 `LJG-Source: <sha>` 记录 source，并将它保留为父提交。

- 首次没有 md 分支时，从已验证 source 的提交树创建生成分支，继承已提交根工具；忽略文件、未提交文件不会被采集。
- 已有来源记录时，先对照记录的 base 完整检查技能、根文件和元数据；无漂移才将根范围更新到当前 source。这样 setup/check/install/CI/docs 不会继续停留在旧 md 版本。
- 老 md 没有来源记录时，仅当全部技能内容等于当前 source 的转换结果、根范围等于当前 source，才可进入生成流程。根工具缺失或落后也不会猜测成“可以覆盖”。
- 管理范围内若有 branch-only 文件、手改内容、模式变化、删除或转换器升级造成的差异，直接拒绝，列出路径。范围外已提交文件保留目标父树原状；已有 md 不会同步 source 新增的任意根文件。
- 把有用差异纳入 source 或转换规则并正常评审；保留旧 md 的备份 ref，人工核对新生成结果，再显式完成迁移。本工具没有“忽略差异”“自动丢弃 md”的开关，也不自动迁移或删除真实旧 md 分支。
- 已生成 md 的两份元数据须精确等于记录 source；旧分支只允许内部一致的三处集合版本不同，非版本字段、其他插件或文件模式差异仍拒绝。

转换保留旧有范围：非 assets 的 Org 文件转 Markdown、文件引用同步改名、已知格式指令与结构化强调标签转换、残留检查。正文单星号不做猜测性替换；Org 和同名 Markdown 输出碰撞直接拒绝，绝不覆写一个来保留另一个。

## 验证

```bash
python3 scripts/test_publish.py
```

专项测试使用临时 HOME、隔离 Git 配置/hooks 和禁止真实传输的 Git stub；不要用真实发布替代回归验证。
