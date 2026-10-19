---
name: ljg-book-poster
description: "Create a premium mobile-first long-form visual book note from only a book title or source material. Generate and aggressively compress the reading notes, invent a book-specific visual language, typeset every Chinese/English character in real HTML/CSS, add an in-page one-click PNG export, render a full-page PNG, audit the layout programmatically, and deliver the PNG. Inspired by Apple/Claude clarity and NHK Design Ah! / Layout Song principles of alignment, spacing, scale contrast, and playful re-arrangement. USE WHEN asked for 图书笔记长图, 读书长图, 书籍视觉笔记, HTML转PNG书摘, book poster, visual book notes, or when a user gives a book title and asks for a PNG. NOT FOR direct text-to-image posters where exact typography does not matter."
user_invocable: true
---

# ljg-book-poster：把一本书做成可滑动的视觉读书笔记

目标不是把书评塞进一张长截图，而是把书的关键判断重新编排成一件可以在手机上阅读的视觉作品。

## 流水线（严格执行，不要发明第 7 步）

```text
书名/原文
  ↓ ① 内容压缩：5±1 个核心判断 + 1 清单 + 1 收束
  ↓ ② 视觉语言：1 个母题 + 1 主色 + 1 辅色 + 3 种以上场景类型
  ↓ ③ 写 HTML（一次写完整，不要边写边渲染）
  ↓ ④ python3 scripts/poster.py book.html --outdir out     ← 渲染+审计+裁图+总览图+缩略图
  ↓ ⑤ 读 1 张 sheet（+ 至多 3 张 section crop）定位问题
  ↓ ⑥ 改 HTML，重跑 ④，直到 P1=0 且 P2 已评估
  ↓ 交付 PNG
```

**总预算是 3 轮渲染。** 第 4 轮起说明你在猜。渲染耗时随页面、倍率和机器变化；使用输出的 `captureSeconds` / `auditSeconds` 记录实测，不承诺固定秒数。

## 性能铁律（这两条是历史上最贵的教训）

### 1. 只读一张总览图，禁止逐块盲裁

`poster.py` 已经把所有区块拼成 `out/*-sheet.png`，一张 Read 就能看完整张长图的 9–12 个区块。

- ✅ 先 Read `*-sheet.png`；需要放大时 Read `out/*-sections/03-sec-01.png` 这类**按区块命名的**裁图。
- ❌ 不要再写 `python3 - <<'PY' ... Image.crop((0, 5200, 2880, 6400))` 这种用猜出来的像素坐标裁图。历史上一次生成里有 25 次手工裁剪、42 次读图、6 次重复渲染，全部由此产生。
- ❌ 不要为了"看看对不对"反复渲染。改几处就改几处，攒够一批再渲染。

### 2. 排版问题交给 audit，不要用眼睛找

输出里的 P1/P2/P3 覆盖以下可程序验证的排版问题；不替代内容核对与视觉验收：

| 代码 | 含义 | 处理 |
|---|---|---|
| `T-UNIT-WRAP` | 数字与单位被拆到两行（如 `−13` / `分`） | 数字+单位包一层 `white-space:nowrap` |
| `T-KEY-BREAK` | 强调词被折成两行 | 关键词 `display:inline-block` 并留出空间 |
| `T-WIDOW` | 孤字行：折行文本末行只剩 1 字（任意长度）或正文末行 2 字 | 全局 `text-wrap:pretty`；加宽容器/`white-space:nowrap`，或改写句子回缩上一行 |
| `T-OVERFLOW` / `H-OVERFLOW` | 文字或画布横向溢出 | 查固定宽度子元素 |
| `T-GIANT` | 整句被放大 >80px | 只保留 1 个关键词放大 |
| `BOTTOM-VOID` | 底部大空白 | 主容器写死了高度 |
| `C-CONTRAST` | 对比度不足 | 提明度差，别只靠色相 |
| `SECTION-GAP` / `EDGE-TIGHT` | 区块贴死 / 圆角贴边 | 加间距、加画布 padding |
| `L-FIXED` | 有 fixed/sticky 元素 | 截图会重复渲染，改 static |
| `T-MIN-FONT` | 任一可见文字的计算字号 <70px（P1） | 放大文字、重排或精简，不能缩字塞内容 |

**P1 必须全部修掉，包括任何一处小于 70px 的文字。** P2 逐条判断是否真的影响阅读。P3 可以接受（如轻微对比度）。

## 命令

```bash
python3 ~/.agents/skills/ljg-book-poster/scripts/poster.py book.html --outdir out
```

产物：

| 文件 | 用途 |
|---|---|
| `out/book.png` | 最终长图，默认 1080px 宽（1440 CSS × 0.75）；显式 `--scale 2` 为 2880px |
| `out/book-sheet.png` | **先读这个**：所有区块竖排总览 |
| `out/book-overview.png` | 3 列平铺总览，查节奏与重复感 |
| `out/book-thumb.png` | 独立 QA 缩略图，`--thumb-width` 默认 440px，不决定最终 PNG 宽度 |
| `out/book-sections/*.png` | 按区块命名的裁图，需要放大细节时读 |
| `out/book-audit.json` | 完整审计数据（含区块 y/h、`minFontPx`、`underFloorPx`） |

退出码：`0` = 无 P1；`1` = 有 P1 必须修；`2` = 渲染失败。

两个 CLI 均默认 `--width 1440 --scale 0.75`。最终像素为 `floor(CSS 尺寸 × scale)`；自定义 1560 CSS 宽时 0.75 输出 1170px，不自动变成 1080。不要用 `--width 1080` 或 CSS transform 代替输出倍率。

单独渲染（仍运行审计；JSON 文件按需输出）或显式高清档：

```bash
python3 scripts/render_png.py book.html out.png --width 1440 --scale 2
python3 scripts/contact_sheet.py out.png --out sheet.png          # 只需总览图时
```

## 渲染器为什么可靠（不要绕开它）

- **一次浏览器启动、一次 DOM audit**，固定布局视口；字体状态和图片 decode 明确成功后才截图。lazy 图片主动加载，加载/状态/解码错误退出 2，不发布错误页或替代字体成品。
- **每次截图高、宽不超过 12000 设备 px**，按 `scale` 换算且对齐 CSS/设备坐标。默认 0.75x 为 16000 CSS px，2x 为 6000 CSS px，3x 为 4000 CSS px；这是保守预算，不是所有浏览器的普适极限。最终主图最多 1.6 亿像素，超出明确拒绝。
- 仅截主图分片，拼接完成后所有 sections 从主图裁切；manifest 记录实际 `cropPixels`，sheet 按当前 manifest 顺序生成，overview 等比例缩放。
- PNG 解码验收和全部派生图成功后才发布。POSIX 用单一 `current` 指针切换到新 generation，公共 CLI 文件名不变（符号链接）；交付应复制解引用后的 PNG。Windows 用普通文件／目录、`msvcrt` 单 writer 锁、私有 staging 和备份，在普通异常时逆序回滚，不要求管理员或 symlink 权限。Windows 不是多文件同时可见或 crash/断电原子事务，读取应等待发布结束；恢复失败会保留并报告备份，后续写入拒绝直到人工恢复。跨卷产物组合、未知文件、输入别名、非自有链接／reparse point 一律拒绝。
- 输出目录内 `.poster-*` 为模块拥有的 staging/generation/锁。以下单指针说明仅适用于 POSIX：首次迁移旧普通文件/章节目录时先保留 `legacy-*`，异常回滚；首次别名安装非多路径同时可见。后续完整 `poster.py` 发布单指针切换；多文件读取/复制应在发布完成后进行，跨提交的多次读取不保证快照一致性。旧 generation 成功后回收，不要在渲染同时读取它或手工删除当前 generation。仅 `render_png.py` 重跑时未请求的旧可选产物保留，不代表已重新生成。
- 本地 HTTP 只绑定 loopback，线程化处理、有读取超时且关闭不等待空闲连接。自动渲染禁止外网资源，全部内容依赖须本地化；手动导出库仅在用户按按钮后加载。
- 优先遵守 `CHROMIUM_PATH`（无效路径立即失败）；设置 `PLAYWRIGHT_BROWSERS_PATH` 时使用 Playwright 配套浏览器，不自动切换系统 Chrome。否则按平台发现系统浏览器，Windows 从 `ProgramFiles` / `ProgramFiles(x86)` / `LOCALAPPDATA` 查找 Chrome/Edge。
- JSON、审计源码和 CLI stdout/stderr 使用 UTF-8。QA 标签优先系统 CJK 字体，Windows 包括 `WINDIR/Fonts/msyh.ttc`，缺失时回退随仓文楷；不分发系统字体。Windows 原生运行以专门 CI 的真实结果为准，不把 macOS mock 测试称作 Windows 实跑。

## 硬规则

1. **禁止用生图模型生成最终长图。** 所有书名、中文、英文、副标题、编号、标签、正文都必须是真实 HTML 文本。
2. 生图模型只允许生成**无文字插画素材**，且素材必须服务当前段落。
3. 最终交付优先 PNG；HTML 是母版与复用源。
4. **所有文字至少 70 CSS px**，包括英文、标签、图注、来源、页码、数字单位与生成编号。这是用户设定的硬下限，audit 的 `T-MIN-FONT` 按 70px 判定 P1，低于 70px 一律不许交付。正文优先 70–110px；空间不够时精简、换行、改布局或增加高度，绝不能缩字塞内容。
5. **字体按角色混排，一册使用 5–10 款开源字体**。默认字体库（均为可自由嵌入再分发的开源许可；运行 `scripts/fetch_fonts.sh` 可下载校验好的字体到 `assets/fonts/`）：霞鹜文楷 Regular/Medium（SIL OFL，正文与标题）、得意黑斜体 Smiley Sans Oblique（SIL OFL，书名/大词/序号）、汇文明朝体 Huiwen-mincho（CC0，引文/古典段落）、霞鹜新晰黑 LXGW Neo XiHei（IPA Font License，现代无衬线辅助）、霞鹜马克黑 LXGW Marker Gothic（SIL OFL，趣味强调）。按书的题材选 5–10 款并给每款分配明确角色，同一角色不混用。字体文件复制到本册 `fonts/` 目录，用相对路径 `@font-face` 嵌入（渲染器本地HTTP服务会加载）；`font-display:block` + `document.fonts.ready` 保证字体就绪后才截图。不得改用未授权、未安装或需要联网 CDN 的字体。
5a. **图内不写来源署名与制作说明**。"据作者官网整理""本图不改写为教条口号""示例为转写不是逐字对话""关于这一版/字体署名"这类元信息一律不进图；来源边界、归属区分、许可记录写进 sources.md 与 verification.json，供复查不进成品。图内只保留书本身的内容与必要的版本信息（书名、作者、译者）。
5b. **禁止孤字行（中文排版习惯）**：任何折行的文本，最后一行只剩一个字就不合格——要么把上一行稍微缩回去，要么改写句子。全局启用 `text-wrap:pretty`（有帮助但非保证，CJK 连续字它可能救不回）；固定宽度容器（词标签、序号列）加 `white-space:nowrap` 并预留足够列宽；最终以 audit 的 `T-WIDOW` 渲染后逐节点检测为准，交付前必须为 0。

6. **最终 PNG 可以到约 30000px 高**。默认 0.75x 导出时约为 40000 CSS px（显式 2x 时约 15000 CSS px），内容自然撑高，不写固定高度凑长度。新增高度用于大字、图解、留白、转场与精选模块，不等于增加观点数量。
7. 一句话的字号反差，只放大其中 **1 个最关键的词或短语**。其余文字保持正常阅读字号。
8. 区域编号 `01 / 02 / 03 ...` 要足够大，成为构图元素。
8a. **同一章节标题组合只留一次章号**：大号 `01` 旁不得再写“第 1 章”。副标签用英文主题词（如 SWARM MIND），形成数字／英文／中文三层；无大号数字时，竖排“01 章”可作唯一编号。英文标签仍受 70 CSS px 下限约束。目录和正文的对应编号、正文数据／年份、行动清单不属于重复章号。使用 `.sec-head` 或 `data-chapter-heading` 标记标题组合，以 `.sec-num` / `data-chapter-number` 标记大编号；常见标题／kicker 中重复章号由 `T-CHAPTER-DUP` 作 P2 提示，复杂自定义结构／counter 仍人工复核，不能将无提示等同全图已验证。
9. 尽量取消硬直角矩形。卡片、网格、大章节块统一使用完整圆角。
10. 大章节块上下必须有留白，四个圆角完整露出；相邻大块之间不能贴死。
11. 配色允许大胆，但**对比度优先于漂亮**。禁止低明度差、低色相差造成的难读组合。
12. 不套固定模板。每本书先找视觉概念，再决定版式。
13. **排版结构按这本书的内容定，不按上一本书的结构复刻。** 详见下节"按书定制排版"。
14. **输出前必须看完整张图**（读 `*-sheet.png` 即可满足），不能只检查局部。

## 按书定制排版（不要单调，也不要换皮）

每册长图在开始写 HTML 前，先从这本书的**实际内容**推出结构，而不是沿用上一册的章节顺序和版式。判断依据是这本书"长什么样"：

| 内容特征 | 相应的排版选择 |
|---|---|
| 章节多、结构清晰（方法书、通识书） | 可设"全书章节地图"区块，用编号列出全部章节名；再挑 2–4 个核心章节深入展开，而不是逐章平均用力 |
| 有明确的核心论点链（论述书） | 每个判断一个独立场景：对照、时间线、结构图、阶梯、环形——连续两个区块不用同一种网格 |
| 有大量案例/故事（传记、叙事书） | 用时间线或路径场景承载事件，标注可核验的时间与出处 |
| 有金句、对话（散文、文学） | 用大字号拉出引文场景，标明说话人与出处 |
| 有可核验的数据（科普、商业） | 用数字+单位的 nowrap 场景，注明来源；没有核到原始出处的数字不量化呈现 |
| 章节少、意旨集中（短篇、随笔集） | 用"一词独占"和留白转场，减少区块数量，拉高单区块信息浓度 |

硬性要求：

- **至少 3 种不同的内容场景**（英雄区、对照、时间线、章节地图、概念群、一词独占、结构图、引文、清单、留白转场任选），连续 5 个区块不得使用同一种网格。
- 视觉母题、主色、辅色从这本书的内容出发重新设计；上一册的配色和图形不得直接搬用。
- 全部章节名必须来自可核验来源（出版方目录、官方页）；没有核到就不列，改用"核心内容"表达。
- 字号下限与字体规则不变；场景变化不得以牺牲 70px 下限或对比度为代价。

### 完整章节骨架模式（参考图实验，2026-10-19 验证）

用户提供的优秀参考图证明："清晰、完整"的感觉来自**每章信息层次做全**，而不是堆砌花哨。可选用这套骨架（结构感强、适合章节多的书），也可与判断链模式混用：

```text
封面：CSS 实体书封（竖排书名 + 题签 + 印章 + 书脊阴影）+ 右侧钩子与署名
  ↓
全书地图：目录条目按年份/卷分组列出（条目必须来自已核公开目录）
  ↓
N 个编号章节，每章完整四层：
  章号水印（超大衬线字，低透明度做构图）
  + 标题 + 一句话副标
  + 2–4 条要点（粗体引导词 + 解释行）
  + 引用卡（可选，公版逐字核对才配；核对不过降级为概述）
  + 该章专属无字 SVG
  ↓
收束：大字判断 + 一句马克体收束语
```

要点写法：引导词 4–6 字（如"跨马截水""不杀降将"），解释行 1–2 句；这就是参考图"信息密度感"的来源。

### 渲染器实测坑（本模式踩过的，全部真实发生）

- **flex + writing-mode 竖排会整体丢失**：书封竖排书名用 `display:flex` 装多个 vertical-rl 列，渲染后只剩部分列。修复：每列独立 `position:absolute` + right 偏移，不用 flex 容器。
- **金红低对比**：深红底上金色文字对比度只有 1.2–1.6，审计直接 P2。修复：红底一律用近白 #fdf3dd 做主文字，金色只留细线与印章底色。
- **`white-space:nowrap` 撑破 grid**：给长出版社名加 nowrap 会让整列溢出画布（T-OVERFLOW P1）。固定列里的长词组改为手动 `<br>` 断成 ≤8 字段，而不是 nowrap。
- **9 字以上机构名在窄列必折孤字**：拆成两行短词组（"社会科学 / 文献出版社"），配合逐节点孤字检测验证。
- 新格式第一版预期要 5–7 轮调试（超出 3 轮原则），每轮必须有实质改动并在 verification.json 的 renderRoundsNote 如实记录，不算重复渲染。

## 内容引擎

优先依据用户提供的原书全文核对观点、案例、数据与限定条件，不拿书评代替原著；只做摘要转化，不整段搬运原文。先生成完整理解，再砍掉至少一轮内容。视觉长图保留的是"值得停下来看的东西"，不是章节完整度。

默认可保留：

- 1 个顶部钩子 / 推荐语
- 4–8 个最核心观点
- 1 组行动清单 / 关键提醒
- 1 个结尾收束

每个观点优先写成 1–3 句短句。低价值解释直接删。

成功标准：

> 一眼能读，停下来能想，滑过去有节奏。

## 句内大小字规则

错误做法：整句话全部 80–120px。

正确做法：

```text
财富真正给你的
是越来越大的

选择权
```

上面两行保持舒适主字号，只有『选择权』放大 2–3 倍，并给它独立留白。

关键词周围不要再挤别的字。放大词必须是 `display:inline-block`，否则会被折行（audit 会报 `T-KEY-BREAK`）。

## 版式语言

先读 `references/design-language.md`。

基础原则来自四组语言的融合：

- Apple：克制、清晰、产品级留白
- Claude：现代网页的信息层级与柔和容器
- NHK《Design Ah! / Layout Song》：对齐、重排、尺度突变、空间分组、让排版本身传递意义
- 本 Skill 的长期规则：圆角章节岛、句内单关键词放大、移动端大字号、真实 HTML 文字

**不要把 NHK 理解成"日本风 + 红色 + 竖排"。** 真正要学的是：同样的元素通过对齐、间距、位置、尺寸变化产生新的阅读顺序。

## 视觉构图

长图不是连续白卡片列表。至少使用 3 种不同的内容场景，例如：

- 英雄区：大标题 + 一句钩子 + 封面 / 抽象视觉
- 对照场景：左右两种状态
- 时间 / 路径：沿轨迹推进
- 概念群：不等大的模块形成主次
- 一词独占：一句话后只留一个超大关键词
- 数据 / 结构图：圆环、阶梯、流向、坐标关系
- 安静转场：只保留一句短句与大量留白

连续两个章节不要机械复用完全相同的网格。

## 圆角规则

- 小卡片：建议 20–36px
- 大章节岛：建议 44–72px
- 同一层级保持接近的圆角半径
- 连续 4–6 个块仍然各自圆角，并保持 16–32px 视觉间距
- 大章节岛之间建议 64–120px 垂直间距
- 大块不能贴画布上下边缘

## 字号建议（1440px 宽长图）

以下均为 HTML 母版的 **CSS 字号**，不是导出 PNG 的像素字号。根据书与内容动态调整，但所有可见文字的计算字号不得低于 70px：

最小号提到 70px 后，最大号同步放大 50% 以保持尺度反差（用户 2026-10-19 确认）：

- 书名：180–285px
- 章节编号：225–270px
- 章节标题：96–120px
- 主句：70–90px
- 句内关键词：165–235px
- 卡片标题：70–80px
- 正文 / 辅助文字：70–110px

大字号必须配足留白与行高，防止折行；audit 的 T-KEY-BREAK / T-GIANT 仍会拦截失控放大。

使用 `em`、`rem`、百分比或继承时也必须满足 70px 下限；数字单位可用 `font-size:max(70px,.42em)`。空间不够时精简、换行、改布局或增加高度，不能恢复极小字。

如果用户要求『字体再大一号』，优先放大主句与辅助正文，不只放大标题。如果要求『重新设计』『重来』『完全重构』，从原书内容、视觉隐喻、阅读顺序与场景重新组织，不把旧图简单等比放大；旧版另存保留。

## 配色

视觉语言必须跟书走。

允许：

- 封面色提取
- 多巴胺色
- 黑金 / 暗黑
- 东方留白
- 高明度柔和配色
- 发布会式黑白强对比

禁止：

- 浅黄字 + 浅绿底
- 粉字 + 橙底等低对比组合
- 为了"丰富"同时使用太多强调色

每屏最好只保留 1 个主强调色 + 1 个辅助色。

## 插图

优先顺序：

1. CSS / SVG 几何图形
2. 结构示意图
3. 图标
4. 无文字 3D / 粘土 / 插画素材

任何插图都要回答：删掉它以后，理解是否变差？如果没有，删掉。

按章节内容配画面：每个核心判断区块至少配一段贴合该章内容的无字 SVG 场景（人物动作、关系结构、过程示意、空间隐喻任选），不是装饰性重复母题；同一画面类型全图不重复超过两次。SVG 里的文字一律不进图——含义靠形状与排版传达，caption 用真实 HTML。

## HTML 母版要求

输出单文件 HTML 为优先，页面主容器建议固定宽度 1440px 或 1560px。骨架见 `assets/poster-skeleton.html`（已内置上述排版约束）。

HTML 必须：

- 所有文字可选中、可复制
- 字体优先使用系统 CJK 字体栈
- 避免依赖不稳定的远程字体
- 主容器高度由内容自然撑开，不要写超大固定 `min-height` 造成底部空白
- 大模块使用 `border-radius`
- 使用 CSS Grid / Flex 做精确对齐
- 装饰元素不能盖住文字
- 导出按钮使用 `data-export-ignore` 且 `position:static`（避免 `L-FIXED`）
- 数字与单位：`<span class="nowrap">−13<span class="unit">分</span></span>`
- 放大关键词：`display:inline-block`，并在前后留出空间

### 一键导出 PNG

HTML 内默认提供一个『导出 PNG』按钮（用户侧便利功能，自动渲染不用它）。

```html
<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
<script>
async function exportPNG() {
  const tools = document.querySelector('[data-export-ignore]');
  if (tools) tools.style.display = 'none';
  try {
    const node = document.getElementById('poster');
    const canvas = await html2canvas(node, {
      scale: 0.75,
      useCORS: true,
      backgroundColor: getComputedStyle(node).backgroundColor,
      logging: false,
      windowWidth: node.scrollWidth,
      windowHeight: node.scrollHeight
    });
    const a = document.createElement('a');
    a.download = 'book-note.png';
    a.href = canvas.toDataURL('image/png');
    a.click();
  } finally {
    if (tools) tools.style.display = '';
  }
}
</script>
```

上面的 CDN 片段仅说明手动导出接口；实际母版使用 `assets/poster-skeleton.html` 的按钮点击后延迟加载方式，不在自动截图时请求 CDN。自动化最终 PNG 一律使用 `scripts/poster.py`。

## 最终 QA

`poster.py` 自动检查文本 Range 与祖先 overflow 裁剪区、跨内联节点和尾部空白的末行孤字、强调词折行、数字单位断行、整句放大、对比度、间距、底部空白、fixed 元素及 70px 下限。孤字没有大标题字号豁免；正文两字尾行仍作 P2 提醒。字号计入祖先 transform / scale / zoom 的最小二维尺度，覆盖 `::before` / `::after` / 原生 `::marker`；隐藏内容与导出工具不计入。`minFont` 必须 ≥70px，`underFloorPx=0`。复杂透视、非矩形 clip-path、视觉遮挡和审美仍需人工检查。

剩下这些**必须靠人眼读图**判断，用 `*-sheet.png` + `*-thumb.png` 各一次即可：

### 看图
- 手机缩略图状态下能否一眼区分标题 / 主句 / 关键词
- 是否有『丑、散、空、挤』中的任何一种
- 是否连续 5–8 个章节都长得一样
- 插图 / 装饰是否真的在帮理解（删掉会不会更好）

### 看字
- 书名、作者、英文、副标题是否正确
- 有无错字、漏字、乱码
- **汇文字形 QA（凡用汇文明朝体必做）**：风险字集合 `让药继赞钟钥认讲论证铁` 来自 v3.3.0 分支经验，不是所有版本的字形证明。audit 的 `huiwenReview` 从可见文本／生成文字中筛选请求 Huiwen/汇文/匯文字体的候选；自定义字体别名用 `data-glyph-review="huiwen"` 标记该段。字体声明与逐字实际 fallback 不等同，报告明确为 `manual-review-required`，零候选也不表示所有字形正确。按本册固定字体文件，取候选与新增字符渲成 **120px 字符网格**逐字目检，再核对成品实际字形。仅对应字体段落受该清单约束，其他字体不全局禁字。引文、书名、人名和术语不得自动改写，优先为该段换合规字体；摘要文案改写须语义不变。不要把“钥匙→入口”等例子当机械替换表，也不宣称其他字体永远无问题
- 是否真正做到一句只突出一个关键词

## 失败处理

| 现象 | 处理 |
|---|---|
| 渲染失败 / 页面高度 <10px | 查 `display:none`、固定高度、JS 报错 |
| `L-FIXED` 报错 | 导出按钮改 `position:static` |
| 最终 PNG 超出期望长度 | 先精简重复内容、调整节奏，不缩小到 70px 以下；约 30000 PNG px 在 2x 时约为 15000 CSS px，不是固定上限 |
| Playwright 未安装 | `python3 -m pip install playwright pillow`，浏览器用系统 Chrome 即可 |
| 需要超过 2x 的清晰度 | `--scale 3`（文件会显著变大，通常没必要） |
| Windows 标签方框 | 检查雅黑或随仓文楷；Arial 能加载不代表含中文字形 |
| PNG 超出像素预算 / Pillow 大图错误 | 保留 1.6 亿像素限制，降低导出倍率或精简内容，不设置全局 `Image.MAX_IMAGE_PIXELS = None` |
| Windows 依赖下载受代理阻塞 | 先检查当前会话代理与网络；仅在确认失效代理后临时修正，不由渲染器修改全局代理／Git 配置 |

**不要做的事：** 不要用 PDF 分页再拼 PNG；不要 `full_page=True` 截超长页（>16384 设备像素会压缩并出现黑带）；不要用猜的像素坐标手工裁图。

## 输出

默认只交付：

1. 可点击下载的 PNG 链接
2. 简短说明尺寸与视觉方向

**默认交付 1080px 宽 PNG**：保持 1440 CSS 母版，仅将输出倍率设为 0.75；70 CSS px 的有效字号下限不变，输出的名义 em 约 52.5px。`--scale` 不进入 CSS 字号审计，CSS transform/zoom 缩字仍会被拦截。2880 高清档用 `--scale 2` 按需交付；文件体积不保证固定缩减比例。HTML 手动导出按钮同样默认 0.75，但不能替代自动渲染器的分片和 QA。

用户需要时再补 HTML。

永远不要只返回本地文件路径。必须提供真正可下载/可访问的文件链接或明确上传位置。

## 维护验证

模块正式回归：`python3 -m unittest discover -s skills/ljg-book-poster/scripts -p 'test_*.py'`（仓库根运行）；在模块目录运行时 `-s scripts`。测试覆盖真实浏览器排版与字体加载、默认 1080 / 显式 2x / 自定义宽度、0.75 跨分片与 9000 CSS px 章节 2x/3x、分片像素/裁切一致性、旧章节、资源失败、URL 编码、UTF-8 输出、退出码、两种事务失败回滚/别名安全及本地服务阻塞。Windows 仅跳过 POSIX 专用 generation/symlink 测试与 `fetch_fonts.sh` 维护工具测试，真实渲染与 portable 事务测试照常执行。所有夹具使用自动清理的 tempdir，外部资源默认拒绝，不下载字体。

直接依赖见本模块 `requirements.txt`（playwright 1.58.0 / Pillow 11.3.0；不是传递依赖完整锁）。使用项目隔离环境与对应 Playwright Chromium；本机可显式 `CHROMIUM_PATH` 覆盖。不得为了测试去安装全局依赖或运行已安装技能副本。

## 通用提示词

完整的可移植提示词见 `references/universal-prompt.md`。
