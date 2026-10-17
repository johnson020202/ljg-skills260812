---
name: ljg-book-poster
description: "Create a premium mobile-first long-form visual book note from only a book title or source material. Generate and aggressively compress the reading notes, invent a book-specific visual language, typeset every Chinese/English character in real HTML/CSS, add an in-page one-click PNG export, render a full-page PNG, visually QA the result, and deliver the PNG. Inspired by Apple/Claude clarity and NHK Design Ah! / Layout Song principles of alignment, spacing, scale contrast, and playful re-arrangement. USE WHEN asked for 图书笔记长图, 读书长图, 书籍视觉笔记, HTML转PNG书摘, book poster, visual book notes, or when a user gives a book title and asks for a PNG. NOT FOR direct text-to-image posters where exact typography does not matter."
user_invocable: true
---

# ljg-book-poster：把一本书做成可滑动的视觉读书笔记

目标不是把书评塞进一张长截图，而是把书的关键判断重新编排成一件可以在手机上阅读的视觉作品。

最终路线固定为：

```text
书名 / 原文
  ↓
理解书籍与筛选内容
  ↓
决定本书专属视觉语言
  ↓
HTML/CSS 精准排版真实文字
  ↓
HTML 内置一键 PNG 导出
  ↓
浏览器整页渲染 PNG
  ↓
视觉 QA
  ↓
只交付合格 PNG
```

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
12. 输出前必须看完整张图，不能只检查局部。

## 内容引擎

先生成完整理解，再砍掉至少一轮内容。视觉长图保留的是“值得停下来看的东西”，不是章节完整度。

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

关键词周围不要再挤别的字。

## 版式语言

先阅读 `references/design-language.md`。

基础原则来自四组语言的融合：

- Apple：克制、清晰、产品级留白
- Claude：现代网页的信息层级与柔和容器
- NHK《Design Ah! / Layout Song》：对齐、重排、尺度突变、空间分组、让排版本身传递意义
- 本 Skill 的长期规则：圆角章节岛、句内单关键词放大、移动端大字号、真实 HTML 文字

**不要把 NHK 理解成“日本风 + 红色 + 竖排”。** 真正要学的是：同样的元素通过对齐、间距、位置、尺寸变化产生新的阅读顺序。

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
- 为了“丰富”同时使用太多强调色

每屏最好只保留 1 个主强调色 + 1 个辅助色。

## 插图

优先顺序：

1. CSS / SVG 几何图形
2. 结构示意图
3. 图标
4. 无文字 3D / 粘土 / 插画素材

任何插图都要回答：删掉它以后，理解是否变差？如果没有，删掉。

## HTML 母版要求

输出单文件 HTML 为优先，页面主容器建议固定宽度 1440px 或 1560px。

HTML 必须：

- 所有文字可选中、可复制
- 字体优先使用系统 CJK 字体栈
- 避免依赖不稳定的远程字体
- 主容器高度由内容自然撑开，不要写超大固定 `min-height` 造成底部空白
- 大模块使用 `border-radius`
- 使用 CSS Grid / Flex 做精确对齐
- 装饰元素不能盖住文字
- 导出按钮使用 `data-export-ignore` 或导出时隐藏

### 一键导出 PNG

HTML 内默认提供一个『导出 PNG』按钮。

若允许远程依赖，可使用 `html2canvas`：

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

这个按钮是用户侧便利功能。自动化最终 PNG 优先使用本 Skill 的 `scripts/render_png.py`。

## PNG 渲染

运行：

```bash
python skills/ljg-book-poster/scripts/render_png.py input.html output.png
```

渲染脚本优先使用 Playwright + Chromium 整页截图。整页截图失败时，才允许回退到分段坐标截图并无损拼接。

**不要用 PDF 分页后再拼 PNG。** 这会重新分页布局，容易出现重复、断层、圆角被切断。

## 最终 QA

交付前逐项检查：

### 文字

- 书名、作者、英文、副标题是否正确
- 有无错字、漏字、乱码
- 是否存在过多小字
- 是否出现整句话全部巨大化
- 是否真正做到一句只突出一个关键词

### 版式

- 手机缩略图状态下能否一眼区分标题 / 主句 / 关键词
- 章节编号是否足够大
- 对齐关系是否明确
- 留白是否主动参与分组
- 是否连续 5–8 个章节都长得一样
- 是否有『丑、散、空、挤』中的任何一种

### 圆角

- 大块四角是否完整
- 大块与画布上下是否留白
- 相邻章节岛是否有距离
- 小卡片是否还残留无意义直角

### 色彩

- 所有文字与背景是否具有足够对比度
- 强调色是否过多
- 封面色是否与全图产生关系

### 输出

- PNG 是否完整
- 底部是否出现大段空白
- 是否裁切内容
- 是否模糊
- 是否出现重复接缝 / 断层 / 位移

## 失败处理

- 整页 PNG 底部空白：先查 HTML 主容器是否写死高度；裁切只能作为最后补救，不是默认方案。
- 浏览器超长截图超时：先减少阴影、滤镜、复杂 SVG，再回退分段坐标截图。
- 分段必须按真实 CSS 像素 Y 坐标裁切，禁止 PDF 分页。
- 生图文字错误：不要修图，直接回到 HTML 真文字流程。
- 用户说『重来』『完全重构』：不能在旧版上微调。重新从书籍内容、视觉隐喻和版式节奏开始构图。

## 输出

默认只交付：

1. 可点击下载的 PNG 链接
2. 简短说明尺寸与视觉方向

用户需要时再补 HTML。

永远不要只返回本地文件路径。必须提供真正可下载/可访问的文件链接或明确上传位置。

## 通用提示词

完整的可移植提示词见 `references/universal-prompt.md`。
