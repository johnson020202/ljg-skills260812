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

**总预算是 3 轮渲染。** 第 4 轮起说明你在猜。渲染本身只要约 10 秒，贵的是每轮之后的读图和返工。

## 性能铁律（这两条是历史上最贵的教训）

### 1. 只读一张总览图，禁止逐块盲裁

`poster.py` 已经把所有区块拼成 `out/*-sheet.png`，一张 Read 就能看完整张长图的 9–12 个区块。

- ✅ 先 Read `*-sheet.png`；需要放大时 Read `out/*-sections/03-sec-01.png` 这类**按区块命名的**裁图。
- ❌ 不要再写 `python3 - <<'PY' ... Image.crop((0, 5200, 2880, 6400))` 这种用猜出来的像素坐标裁图。历史上一次生成里有 25 次手工裁剪、42 次读图、6 次重复渲染，全部由此产生。
- ❌ 不要为了"看看对不对"反复渲染。改几处就改几处，攒够一批再渲染。

### 2. 排版问题交给 audit，不要用眼睛找

`:code` 输出里的 P1/P2/P3 已经覆盖了历史上所有真实 bug：

| 代码 | 含义 | 处理 |
|---|---|---|
| `T-UNIT-WRAP` | 数字与单位被拆到两行（如 `−13` / `分`） | 数字+单位包一层 `white-space:nowrap` |
| `T-KEY-BREAK` | 强调词被折成两行 | 关键词 `display:inline-block` 并留出空间 |
| `T-WIDOW` | 末行只剩 1–2 字 | 改 `max-width` 或改写句子 |
| `T-OVERFLOW` / `H-OVERFLOW` | 文字或画布横向溢出 | 查固定宽度子元素 |
| `T-GIANT` | 整句被放大 >80px | 只保留 1 个关键词放大 |
| `BOTTOM-VOID` | 底部大空白 | 主容器写死了高度 |
| `C-CONTRAST` | 对比度不足 | 提明度差，别只靠色相 |
| `SECTION-GAP` / `EDGE-TIGHT` | 区块贴死 / 圆角贴边 | 加间距、加画布 padding |
| `L-FIXED` | 有 fixed/sticky 元素 | 截图会重复渲染，改 static |
| `T-SMALL-CENSUS` | <24px 小字超过 16 处 | 合并或删减低价值元信息 |

**P1 必须全部修掉。** P2 逐条判断是否真的影响阅读。P3 可以接受（小字普查、轻微对比度）。

## 命令

```bash
python3 ~/.agents/skills/ljg-book-poster/scripts/poster.py book.html --outdir out
```

产物：

| 文件 | 用途 |
|---|---|
| `out/book.png` | 最终长图，默认 2880px 宽（1440 CSS × 2） |
| `out/book-sheet.png` | **先读这个**：所有区块竖排总览 |
| `out/book-overview.png` | 3 列平铺总览，查节奏与重复感 |
| `out/book-thumb.png` | 手机宽度缩略图，查"一眼能否分清层级" |
| `out/book-sections/*.png` | 按区块命名的裁图，需要放大细节时读 |
| `out/book-audit.json` | 完整审计数据（含每个区块 y/h） |

退出码：`0` = 无 P1；`1` = 有 P1 必须修；`2` = 渲染失败。

单独渲染（不审计）或换参数：

```bash
python3 scripts/render_png.py book.html out.png --width 1440 --scale 2
python3 scripts/contact_sheet.py out.png --out sheet.png          # 只需总览图时
```

## 渲染器为什么可靠（不要绕开它）

- **一次浏览器启动**，`networkidle` + `document.fonts.ready` 后直接 CDP 截图，不滚动、不分页。
- **切片按 CSS 像素裁切**，每片 6000 CSS px，远低于 Chrome 约 16384 设备像素的单张上限；`clip.scale=2` 由 Chrome 原生渲染，清晰度与 `device_scale_factor=2` 相同（已实测边缘锐度一致）。
- 切片与单张整页截图**逐像素一致**，不存在接缝。
- 页面再长也不会触发「压缩 + 黑带」问题——那正是旧版 `full_page=True` 在 >16384px 时的故障。

## 硬规则

1. **禁止用生图模型生成最终长图。** 所有书名、中文、英文、副标题、编号、标签、正文都必须是真实 HTML 文本。
2. 生图模型只允许生成**无文字插画素材**，且素材必须服务当前段落。
3. 最终交付优先 PNG；HTML 是母版与复用源。
4. 手机阅读优先。字号宁可大，不要为了塞内容把字缩小。
5. 长图可以很长。增加高度用于留白、节奏、插图、转场和精选模块，不用来堆小字。
6. 一句话的字号反差，只放大其中 **1 个最关键的词或短语**。其余文字保持正常阅读字号。
7. 区域编号 `01 / 02 / 03 ...` 要足够大，成为构图元素。
8. 尽量取消硬直角矩形。卡片、网格、大章节块统一使用完整圆角。
9. 大章节块上下必须有留白，四个圆角完整露出；相邻大块之间不能贴死。
10. 配色允许大胆，但**对比度优先于漂亮**。禁止低明度差、低色相差造成的难读组合。
11. 不套固定模板。每本书先找视觉概念，再决定版式。
12. **输出前必须看完整张图**（读 `*-sheet.png` 即可满足），不能只检查局部。

## 内容引擎

先生成完整理解，再砍掉至少一轮内容。视觉长图保留的是"值得停下来看的东西"，不是章节完整度。

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

根据书与内容动态调整，默认范围：

- 书名：96–150px
- 章节编号：130–180px
- 章节标题：54–76px
- 主句：40–56px
- 句内关键词：88–150px
- 卡片标题：30–40px
- 辅助正文：26–34px
- 极小元信息：18–24px，严格少用

如果用户要求『字体再大一号』，优先放大主句与辅助正文，不只放大标题。

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
      scale: 2,
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

自动化最终 PNG 一律使用 `scripts/poster.py`。

## 最终 QA

`poster.py` 已自动完成：溢出、孤字、强调词折行、数字单位断行、整句放大、对比度、区块间距、贴边、底部空白、fixed 元素、小字普查。

剩下这些**必须靠人眼读图**判断，用 `*-sheet.png` + `*-thumb.png` 各一次即可：

### 看图
- 手机缩略图状态下能否一眼区分标题 / 主句 / 关键词
- 是否有『丑、散、空、挤』中的任何一种
- 是否连续 5–8 个章节都长得一样
- 插图 / 装饰是否真的在帮理解（删掉会不会更好）

### 看字
- 书名、作者、英文、副标题是否正确
- 有无错字、漏字、乱码
- 是否真正做到一句只突出一个关键词

## 失败处理

| 现象 | 处理 |
|---|---|
| 渲染失败 / 页面高度 <10px | 查 `display:none`、固定高度、JS 报错 |
| `L-FIXED` 报错 | 导出按钮改 `position:static` |
| 页面 > 30000 CSS px | 内容过多，删减，不要加大切片数 |
| Playwright 未安装 | `python3 -m pip install playwright pillow`，浏览器用系统 Chrome 即可 |
| 需要超过 2x 的清晰度 | `--scale 3`（文件会显著变大，通常没必要） |

**不要做的事：** 不要用 PDF 分页再拼 PNG；不要 `full_page=True` 截超长页（>16384 设备像素会压缩并出现黑带）；不要用猜的像素坐标手工裁图。

## 输出

默认只交付：

1. 可点击下载的 PNG 链接
2. 简短说明尺寸与视觉方向

用户需要时再补 HTML。

永远不要只返回本地文件路径。必须提供真正可下载/可访问的文件链接或明确上传位置。

## 通用提示词

完整的可移植提示词见 `references/universal-prompt.md`。
