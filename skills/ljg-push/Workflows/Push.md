# Push Workflow

## 1. 明确发布范围

使用本次实际加载的 `{skill_dir}/Tools/Push.sh`。默认仓库 `~/code/ljg-skills260812`，安装源 `~/.agents/skills`，身份 `johnson020202/ljg-skills260812`，source=`master`、generated=`md`。非默认位置显式给 `--repo`、`--local`；单技能用 `--skill ljg-xxx`。唯一兼容名 `fix-ljg-org-to-md` 也可显式选择并参与默认发现；任意其他非 `ljg-*` 名称或路径仍拒绝。

发布对外发送用户内容，只有用户确实要求发布时才运行正式命令；修复、审计或预览请求只运行隔离测试 / dry-run。

## 2. 只读预检

```bash
bash {skill_dir}/Tools/Push.sh --repo /path/to/repo --dry-run
```

检查显示的 origin、分支 SHA、技能列表、拟变更路径和版本。工作区/index 必须干净，README 已提交且覆盖技能精确名称。根同步范围为 `README.md`、`CLAUDE.md`、`LICENSE`、`.gitignore`、`scripts/**`、`docs/**`、`.github/**`（`ROOT_PATHS`）；只取 source 已提交的普通文件，不扫描工作目录补缺。两份 `.claude-plugin` 元数据仍单独校验。dry-run 不联网、不写文件；不证明远端一致或凭据有效。

不要绕过以下拒绝：脏仓库、错误分支、不同 origin、路径/symlink 越界、版本不一致、md 未纳管人工差异。`--force` 不是强推开关；`--skip-readme-check` 仅适用于已人工审查的 README，不处理其他拒绝。

## 3. 正式发布

```bash
bash {skill_dir}/Tools/Push.sh --repo /path/to/repo
```

执行顺序：

1. 完成全部本地预检及 source/Markdown 转换计划。已有 md 对照记录的 source base 检查整个技能树、根白名单和两份元数据；legacy 没有来源时对照当前 source，只有三处一致的旧集合版本可不同，其余人工或历史差异直接拒绝。
2. `ls-remote` 只读核对两条远端分支；不同基线直接停止，不自动 pull/fetch/rebase。
3. 在独立临时 Git 仓库构建：只暂存明确文件列表，md 同步已提交根工具的新增/更新/删除及执行模式，结构化写三处一致版本，回读包含根文件的完整管理范围，保留 source→md 来源父链。范围外文件保留目标父树，不从 source 任意复制。
4. 再次核对用户仓库/源目录未变化，然后完整 refspec + 精确旧 SHA lease 一次 `push --atomic`。不支持原子推送即报错，无两次 push 备选路径。
5. 删除临时构建目录；原仓库 HEAD、index、工作树不变。成功不创建 tag。

## 4. 报告与失败处理

仅在原子 push 返回成功时报告两个 commit SHA 与集合版本。明确本地仓库未前进，需要操作者显式 fetch/fast-forward 后再发布。只有根范围更新也需生成 md 提交，但不 bump、source SHA 不变；技能和 md 管理范围都无变化时才报告 `Nothing to push`，不要声称生成新版本。

| 拒绝 / 故障 | 处理 |
|-------------|------|
| 仓库不存在 | 操作者明确 clone 所需 fork；脚本不会 clone |
| 工作区/index 脏 | 操作者评审并正常提交/移出，不自动 stash/reset |
| origin 或分支不符 | 核实真实目标，显式选择路径/分支；不要自动换成“看起来相似”的仓库 |
| remote/local SHA 不一致 | 操作者检查远端变化并显式更新；脚本不覆盖历史 |
| md 人工差异或转换器变化 | 按 SKILL.md 的来源契约迁移，保留补丁，不静默删除 |
| 写入、版本回读、转换或提交验证失败 | 停止；用户工作树没有修改，未发起 push |
| push 失败 / 不支持 atomic | 停止，无部分发布 fallback；网络中断若状态不明先核对远端 |

## 专项验收

运行 `python3 scripts/test_publish.py`。测试仅在临时 HOME / Git 仓库操作，全部网络传输被 stub 拦截。真实远端权限和服务端 atomic 支持不属于这组离线测试的已验证项。
