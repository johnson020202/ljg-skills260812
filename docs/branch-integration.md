# 分支与新增内容整合

## 固定的来源

本轮在已有可靠性修复上，核对并纳入以下远端分支内容，而非直接用旧分支文件覆盖修复版：

| 分支 | 核对提交 | 内容与处理 |
|---|---|---|
| `master` | `7cdcf235f1a26195c37c7abd5b414b6609c50a6f` | 上一轮审计基线及本地可靠性修复 |
| `book-poster-v3.3.0-windows-qa` | `cbf877db3ee194f6748b99293d317fb8d33b308e` | Windows 路径／编码、1080 成品默认、章号去重、汇文字形 QA；保留已有分片、资源与事务修复 |
| `md` | `920a96fbd8542f9d2372dadc5464eab1b784e7e7` | Markdown 输出契约及独有维护技能；修复真实转换接缝，提供完整离线构建 |

`md` 中六个独有 `.md` 模板对应源分支的六个 `.org` 模板，不是六个新技能。其唯一额外技能是 `fix-ljg-org-to-md`，现已安全迁入；集合共有 **23 个技能**。旧分支的 book/paper/structure 人工修订已在转换逻辑中覆盖，不用逐个回放历史提交来覆盖新修复。

本表记录整合时的输入提交。2026-10-20 按用户明确要求，以集合 1.21.0 / 长图标签 v3.3.0 发布整合结果；原 `book-poster-v3.3.0-windows-qa` 分支保留，不重写历史。构建工具自身不会自动提交、推送或覆盖用户已经安装的技能，单独生成的本地副本也不等于一次 Git 发布。

## 图书长图新增行为

- 默认设计宽度仍是 **1440 CSS px**，最低字号仍是 **70 CSS px**。
- 两个 CLI 默认 `scale=0.75`，最终 PNG 宽 **1080 像素**。显式 `--scale 2` 可得到 **2880 像素**宽版本；`--width 1600` 搭配默认倍率得到 1200 像素宽，而不是强制缩回 1080。
- `--thumb-width 440` 是独立手机缩略图参数，不等于最终交付宽度。
- Windows 增加 Chrome／Edge 发现、UTF-8 文本和控制台处理；显式 `CHROMIUM_PATH` 错误不会静默忽略。
- POSIX 保持 generation 与公开别名；Windows 使用普通文件、字节锁、暂存和备份，普通异常逆序回滚，不依赖创建 symlink 的权限。回滚失败保留可恢复备份，不能把它当垃圾删除后重试。
- 两个平台都不承诺断电／强杀下的多文件原子快照。Windows 上尤其不承诺所有公开文件同时可见。
- 章号去重新增局部结构提示；汇文 QA 提供需要人工查看的候选。字体声明、候选检测不证明真实字形正确，不自动修改引用、专名或原文。

## Markdown 构建与保护边界

```sh
# 输出目录必须尚不存在
python3 scripts/build_format.py --format md --output "./.cache/markdown-distribution"

# 在源版本和新生成 Markdown 版本中运行完整验证
python3 scripts/check.py --format all
```

构建器复制明确的根文件范围，以及两个插件清单和完整 `skills/`：

```text
README.md  CLAUDE.md  LICENSE  .gitignore
scripts/   docs/      .github/
```

这样 Markdown 副本也有当前修复版的 setup/check、安装包装和 CI，不会在技能已更新时继续沿用旧分支的不安全根脚本。

每个新副本附带 `.format-build.json`，包含源／目标指纹、文件路径、模式和 SHA-256。构建拒绝现有目标、输入目录重叠、大小写／Unicode 别名碰撞及不可读输入；失败不发布部分副本。它读取当前工作副本，是离线测试／交付工具，不能代替发布器的已提交来源校验。

转换器按输出模板、语法块和格式约束处理，保留 URL、代码内容和输入反例；Org 日期等元数据序列化为正确 YAML 类型。现有校验器没有为容忍错误转换而被放松。`fix-ljg-org-to-md` 本身保持格式中立，不再硬编码 Home 路径或自动执行提交／全局删除式同步。

## 发布范围

发布器管理同一组根文件。已存在的 Markdown 分支也会继承源提交中的根工具；仅根工具变化时生成 Markdown 更新，不因格式副本同步而无故递增集合版本。

带来源标记的 Markdown 产物对照记录的 source/base 校验人工漂移；没有标记的旧分支仍严格拒绝不明差异。当前远端旧 `md` 不是可以自动无损覆盖的目录，本轮没有绕过该检查。根范围外的目标分支既有文件保持，不从源工作区夹带任意其他文件。

兼容技能名仅额外允许精确的 `fix-ljg-org-to-md`，不将路径名称检查放宽为任意字符串。

## 验证入口与平台事实

- `python3 scripts/check.py`：验证当前目录。
- `python3 scripts/check.py --format md`：构建完整 Markdown 副本后验证。
- `python3 scripts/check.py --format all`：源版本与 Markdown 副本全部验证。
- `python scripts/setup.py --scope book-poster`、`python scripts/check.py --scope book-poster`：只准备／验证 Python 长图模块，供 Windows 使用，不代表整个仓库的 POSIX 发布流程均支持 Windows。
- `--static` 始终明确标识为静态检查，不得当作运行测试通过。

CI 的 Linux/macOS 任务执行双格式完整检查；Windows 任务执行原生长图模块测试。当前开发宿主是 macOS，Windows 路径／锁的单元测试及普通文件事务模拟只能证明对应逻辑，**不能替代真实 Windows CI 的运行结果**。没有推送前，不声称远端 CI 已通过。

## 本轮实际验收

在 macOS arm64、Bun 1.3.14、Python 3.12.12 与锁定 Playwright 浏览器环境执行 `python3 scripts/check.py --format all`：

- 源版本：**515/515 测试通过**。
- 完整生成的 Markdown 副本：**515/515 测试通过**。
- 共执行 **1030 次测试**，这是同一套回归分别验证两个格式，不是 1030 个互不重复的用例。
- 两份副本的仓库契约、Shell/Python 语法、卡片审计和演示自检均通过。
- 独立评审确认的构建别名、Windows 事务、Markdown 字面保真、超过 100 路径的发布暂存问题均已修复并定向复核关闭。
- 主代理另用原审计 HTML 运行默认长图 CLI，得到 **1080×1035 PNG**、**440×422 thumbnail**，确认倍率与缩略图参数独立。

正式结果在 `.cache/format-check-results.json`，计数摘要在 `.cache/branch-integration-test-summary.json`。这些是本机验证，不含原生 Windows CI 或真实远端发布。
