# ljg-skills

基于 [lijigang 的原项目](https://github.com/lijigang/ljg-skills) 迭代的自定义技能集。此仓库的安装与发布目标是 `johnson020202/ljg-skills260812`；原作者署名与 MIT 许可证保留。

当前集合版本为 **1.21.0**，读书长图版本为 **3.3.0**（标签 `v3.3.0`）。`master` 是源版本，`md` 是对应的 Markdown 构建分支；未发布的本地修改不会自动出现在远端分支。

## 安装

使用 [skills CLI](https://github.com/vercel-labs/skills) 安装到 Codex：

```bash
# 安装全部技能（全局，org-mode 格式）
bunx skills add johnson020202/ljg-skills260812 -g -a codex --skill '*' -y

# 安装全部技能（Markdown 格式，适用于 Obsidian / VSCode / Notion 等）
bunx skills add johnson020202/ljg-skills260812#md -g -a codex --skill '*' -y

# 安装单个技能
bunx skills add johnson020202/ljg-skills260812 -g -a codex --skill ljg-card -y

# 安装单个技能（Markdown 格式）
bunx skills add johnson020202/ljg-skills260812#md -g -a codex --skill ljg-card -y

# 安装多个指定技能
bunx skills add johnson020202/ljg-skills260812 -g -a codex --skill ljg-card --skill ljg-learn -y

# 查看仓库中有哪些技能
bunx skills add johnson020202/ljg-skills260812 -l
```

**参数说明：**

| 参数 | 作用 |
|------|------|
| `-a codex` | 只安装给 Codex |
| `-g` | 全局安装到 `~/.agents/skills/`（推荐）；不加则安装到项目级 `.agents/skills/` |
| `--skill <name>` | 指定安装某个技能，可重复使用 |
| `--skill '*'` | 安装仓库内全部技能 |
| `#md` | 从 `md` branch 安装 Markdown 格式版本（默认为 org-mode） |
| `-y` | 跳过交互确认 |
| `-l` | 仅列出可用技能，不安装 |

### 运行依赖

纯内容技能无需统一安装浏览器；实际依赖以各技能说明为准。涉及工具调用时，需要 Bun **1.3.14 或更新版本**、Python **3.9 或更新版本**。开发与 CI 固定使用 Bun 1.3.14、Python 3.12。

- `ljg-card`、`ljg-classic`：在**实际安装的技能目录**执行 `bun install --frozen-lockfile --ignore-scripts`，再执行 `bun node_modules/playwright/cli.js install chromium --only-shell`。两个模块使用各自锁定的 Playwright 版本，浏览器不能随意混用。
- `ljg-book-poster`：在实际技能目录创建隔离 Python 环境，再安装 `requirements.txt`，执行 `python -m playwright install chromium --only-shell`。调用 `poster.py` 时使用该环境的 Python。该文件锁定直接依赖，尚非带哈希的传递依赖锁。
- `ljg-present`：校验器使用成熟的 JavaScript／HTML 实体解析依赖；在实际技能目录执行 `bun install --frozen-lockfile --ignore-scripts`。生成的演示 HTML 仍可离线运行，不需要这些开发依赖。
- `ljg-blind` 的本地会话提取使用 Python 标准库，不需要读取其他用户的目录；数据源与时区可显式指定。

项目级安装时，技能目录是 `<项目>/.agents/skills/<技能名>`，不是全局目录。宿主应从当前加载的技能路径定位工具，避免执行另一份旧版本。

### 开发与完整验证

以下命令在克隆的仓库根目录执行，只准备本仓库的依赖，不安装或覆盖用户技能，也不发布：

```bash
python3 scripts/setup.py
python3 scripts/check.py
```

`setup.py` 创建 `.venv/`、安装各模块锁文件依赖，并将匹配浏览器放进 `.cache/ms-playwright/`。Linux 缺少系统库时可显式使用 `--with-deps`，该选项可能需要管理员权限。只装包可用 `--skip-browsers`，但这不代表浏览器测试已通过。

`check.py` 检查安装身份、插件版本一致性、完整技能索引、语法与全部正式回归，并运行现有卡片／演示自检。结果写入 `.cache/check-results.json`，任一失败均返回非零；`--static` 仅检查契约和语法，不代替完整验证。

仓库内 `bash scripts/install.sh` 是 `setup.py` 的兼容入口。它不执行推送。

可靠性修复、审计问题与测试的对应关系、产物迁移及发布限制见 [可靠性说明](docs/reliability.md)。

### 分支整合与离线格式构建

本地整合版包含 `book-poster-v3.3.0-windows-qa` 的新增功能，并保留 `md` 分支独有的 `fix-ljg-org-to-md` 维护技能。后者现在只构建新副本，不自动提交或删除式同步全局技能。

```bash
# 必须使用尚不存在的输出目录；包含完整技能、根级检查工具与 CI
python3 scripts/build_format.py --format md --output "./.cache/markdown-distribution"

# 在同一份源码及其生成的 Markdown 副本上各跑完整验证
python3 scripts/check.py --format all
```

输出目录附带 `.format-build.json` 文件清单和哈希；构建不修改源码或现有输出目录。`--format md` 可只验证 Markdown 副本，`--format org` 构建器选项可导出原格式副本。生成副本不是 Git 发布，不会移动远端分支；旧 `md` 的人工差异仍须显式迁移，不能绕过发布保护。

### Windows 读书长图

Windows 使用独立的 Python 渲染验证范围，不承诺整个 POSIX 发布工具链支持 Windows：

```text
python scripts/setup.py --scope book-poster
python scripts/check.py --scope book-poster
```

长图默认保持 1440 CSS px 布局、以 `0.75` 倍导出 **1080 像素宽**成品；`--scale 2` 仍可显式导出 2880 像素宽版本。手机缩略图的 `--thumb-width 440` 是另一项参数。章节序号去重、汇文字形检查及 Windows 路径／编码规则详见该技能说明。各分支来源、转换边界与平台验证范围见 [分支整合说明](docs/branch-integration.md)。

### 替代方式：git clone

仓库根目录不是技能目录，clone 后还要把 `skills/` 同步到 Codex。下面两种格式二选一：

```bash
# org-mode 版本（master）
git clone --branch master --depth 1 https://github.com/johnson020202/ljg-skills260812.git "$HOME/code/ljg-skills"
mkdir -p "$HOME/.agents/skills"
rsync -a "$HOME/code/ljg-skills/skills/" "$HOME/.agents/skills/"

# Markdown 版本（md）
git clone --branch md --depth 1 https://github.com/johnson020202/ljg-skills260812.git "$HOME/code/ljg-skills-md"
mkdir -p "$HOME/.agents/skills"
rsync -a "$HOME/code/ljg-skills-md/skills/" "$HOME/.agents/skills/"
```

## 技能

| 技能 | 说明 |
|------|------|
| **ljg-blind** | 盲区扫描 — 读取指定日期的 AI 对话，找出结构性思维盲区，并用微信读书章节精准补上 |
| **ljg-book-poster** | 读书长图 — 从图书材料生成 HTML 与长 PNG，统一输出排版审计、章节裁图和总览 |
| **ljg-card** | 内容铸卡 — 将文本铸成四种 PNG 视觉卡片（长图 `-l`、多卡 `-m`、漫画 `-c`、白板 `-w`）；所有模式统一使用文本生成位图，不再使用 SVG |
| **ljg-classic** | 古文精读 — 将原文、逐字注解、句义、章节意旨图与全章解读排成一张可连续阅读的长 PNG |
| **ljg-learn** | 概念解剖 — 从八个方向切开一个概念（历史、辩证、现象、语言、形式、存在、美感、元反思），压成一句顿悟 |
| **ljg-paper** | 论文阅读 — 从一个具体案例开始，让证据暴露旧解释的缺口，再看论文怎样改写框架、操作、证据或可行范围 |
| **ljg-book** | 拆书 — 用一条贯穿张力串起若干具体场景：让旧理解先运行，再由书内证据逐层改写判断与行动，最后回到开头 |
| **ljg-qa** | 信息提问机 — 把文章/论文/书的核心观点抽成 Q-A 链，Q 切要害，A 四段（结论 / 形式化 / 步骤 / 边界） |
| **ljg-plain** | 白话引擎 — 把任何内容改写到聪明的十二岁小孩也能懂 |
| **ljg-rank** | 降秩引擎 — 给一个领域，找出背后不可再少的独立生成器 |
| **ljg-constraint** | 约束引擎 — 给一个领域/专业/角色，找出框住它的那几条约束（硬/软/自设三层），揪出被当成硬约束的假墙、指出哪条能重新定义 |
| **ljg-is** | 本质提炼器 — 剥掉身份、边界、质量和实现，保留最小状态变化，再压成可解释结构式，用跨域迁移检验本质是否真正成立 |
| **ljg-think** | 追本之箭 — 给一个观点或现象，纵向深钻到不可再分的本质 |
| **ljg-word** | 单词精通 — 深度拆解一个英语单词的核心语义和顿悟时刻 |
| **ljg-writes** | 写作引擎 — 把一个观点写成可理解、可迁移、经得住反例的中文文章 |
| **ljg-invest** | 投资分析 — 核心判断项目是否是一台「秩序创造机器」 |
| **ljg-read** | 伴读 — 陪你读任何文本，英文三层翻译（信达雅）+ 结构标注 + 深度提问 + 跨领域旁逸 |
| **ljg-relationship** | 关系分析 — 五层结构诊断 + 精神分析，通过对话引导帮用户"看见"关系真实结构 |
| **ljg-roundtable** | 圆桌讨论 — 一个议题一场圆桌：真实人物逐轮交锋，每轮收一张 ASCII 结构图，散场全文存档 |
| **ljg-structure** | 母题结构风洞 — 从表层问题找到反复出现的母题，提炼可迁移结构，用 ASCII 图说明关系并设计最小可逆实验 |
| **ljg-present** | 演讲铸造器 — 默认高桥流（一页一关键词、奶白底墨字）；`-s` 标语流（VACAT/BIG STUDIOS 风：黑红双色块、ultra-bold、完整断言句撑屏）|
| **ljg-push** | 推送引擎 — 在安全预检后构建并原子发布 master + md 双分支，不改用户工作树 |
| **fix-ljg-org-to-md** | 格式维护 — 安全构建并验证完整 Markdown 副本；不自动提交、推送或覆盖用户技能 |


## 输出格式

技能提供两种输出格式，通过不同 branch 安装。格式分支的实际功能以其发布提交为准；不要假定两个分支始终同步：

| Branch | 格式 | 适用场景 |
|--------|------|----------|
| `master`（默认） | Org-mode（`.org`） | Emacs / Denote 用户 |
| `md` | Markdown（`.md`） | Obsidian / VSCode / Notion 等 Markdown 生态用户 |
