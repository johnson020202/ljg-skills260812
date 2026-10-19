---
name: ljg-blind
description: 盲区扫描——从获授权且已支持的本地 AI 会话数据源读取昨天的真人文本，照出暴露的思维盲区（不是不懂的知识，是让某类真相一直看不见的思维习惯），再从微信读书挑一本书的一章精准补上，落成一篇完整分析笔记。Use when user says '扫盲区', '盲区', '照盲区', '看看我的思维盲区', '我昨天想漏了什么', 'blind spot', 'ljg-blind', '/ljg-blind', or wants yesterday's AI conversations analyzed for cognitive blind spots plus a targeted weread chapter to fill them. 可选参数：传一个日期(YYYY-MM-DD)扫那天而非昨天。NOT FOR 纵向深钻一个观点（用 ljg-think）、一个领域降秩（用 ljg-rank）、陪读一篇文本（用 ljg-read）、找一个领域的约束（用 ljg-constraint）。
user_invocable: true
---

# 盲区扫描

读取已支持且获授权的数据源中昨天的真人文本，照出可能的思维盲区，从微信读书挑出补它的一章。不能把单一宿主的文本当作全部 AI 对话；材料不足就明确停止。

## 盲区是什么

盲区不是知识缺口。不是"没读过某本书""不知道某个事实"——那种缺口，查一下就补上了。

盲区是一种结构性的思维习惯，它让某一类真相对你**系统性地不可见**。你不是想不到，是这个习惯让你压根没往那个方向看。它藏在你怎么想事情的方式里，不藏在你想的内容里。

所以证据不在"他说错了什么"。在——他没往哪看，他在哪绕了，他默认了什么却从没检。

## 五种盲区信号

从昨天的对话里找这五种。每一种都要落到具体的话上，不能凭感觉。

1. **绕开点**——一个难题他打开了，又飞快合上。证据：问题抛出，转头换话题，或一句"这个先不管"滑过去。
2. **空转框架**——反复换视角切同一个问题，没有一个落地。证据：一个问题被套上三四副框架，每副都浅尝辄止，最后没结论。
3. **单一取景框**——一整天只调用一两副 f（逢事就"约束""进化""博弈"），没试过别的镜子。这是他最隐蔽的盲区：越趁手的 f，越挡住别的 f 能照见的东西。（继刚看世界 = f(x)，四轴是他默认的四副 f；正因为默认，才最该查他今天是不是又只用了其中一副。）
4. **未检前提**——一个默认假设贯穿全程，他当硬约束在用，从没问过它是不是假墙。证据：某个"本来就该这样"的说法，反复出现却从未被他自己质疑。
5. **相邻空缺**——从他问的东西反推，本该问、却没问的那个角落。不是凭空猜，是他自己的线索指向那儿。

## 选哪一个

从信号里挑 **1 个**作为今天的盲区。宁可一个说透，不要五个都点一遍——盲区的密度低于精度。判据三条：

- **杠杆**——补上它，下一步打开的可能性最多。
- **真盲**——是他自己看不见的，不是知道了在拖的。
- **对位当前目标**——若用户已在本次对话说明主线，优先选挡住这条主线的盲区；未提供时不假设个人 mission，也不读取作者专属配置。

---

## 操作步骤

### 第一步 · 确认宿主、目录和本地日期

`{skill_dir}` 必须替换为本次实际加载的 `ljg-blind/SKILL.md` 所在绝对目录；项目级、全局和插件安装一律从此目录调用工具，不能回退旧全局副本。

当前自动提取仅支持 **Claude Code** 的 `projects/<project>/<session>.jsonl`，不宣称覆盖所有 AI 宿主。先从当前宿主上下文确认：Codex、LCode、Cursor 等未支持时明确告知，不得因为磁盘上恰有 Claude 日志就暗换数据源；可降级分析用户主动提供的文本/兼容导出。

Python 3.9+ 标准库工具默认使用本地昨天；用户传入 `YYYY-MM-DD` 时用 `--date`。时区默认取 `TZ` 或系统时区数据库，可用 `--timezone Asia/Shanghai` 明确指定。按本地日 `[00:00, 次日00:00)` 过滤，正确解析 `Z`/offset 和夏令时，并以同一时区输出时间；不能用 UTC 日期前缀比较。

### 第二步 · 本地提取当天真人消息

确认宿主和授权后运行（不上传、不调用 API、不写笔记）：

```bash
python3 "{skill_dir}/Tools/extract_conversations.py" --host claude-code
# 指定日期、时区或用户明确提供的合成/导出数据根：
python3 "{skill_dir}/Tools/extract_conversations.py" --host claude-code \
  --date "YYYY-MM-DD" --timezone "Asia/Shanghai" --projects-root "/absolute/path/to/projects"
```

未传 `--projects-root` 时取 `$CLAUDE_CONFIG_DIR/projects`，否则取当前用户 `~/.claude/projects`。不含作者用户名或项目名；仅遍历项目顶层 JSONL，不递归 subagents/workflows，不跟随项目/日志符号链接。字符串与 text block 数组均支持；按角色、来源标记、工具块和消息外层系统包装在**整条消息边界**过滤。`isCompactSummary` / `isVisibleInTranscriptOnly` 等自动摘要标记一律排除；系统标签只认消息开头的外层包装，不搜索正文里的标签。真人问题中的 fenced code、引用和内联标签示例保留，不删词、不按行误杀。仅能报告读取到的真人纯文本，不把图片/附件或缺失宿主的内容说成已读。

stdout 是 JSON，包含本地时间区间、消息列表及可回查的相对来源行号；输出 >50KB 时分段读取，保留消息边界。不要把原始对话交给第三方服务或搜索请求。

- `status=ok`：有至少 200 个非空白文字，可继续分析，但仍需具体证据。
- `status=sparse` / `empty`：正常退出 0；明确写「当前数据源中当天对话稀薄 / 无可用真人文本」，停止盲区推断与选书，不能据此断言所有宿主当天都没对话。
- 退出 2、stderr `status=error`：数据根不可用、无会话文件、不支持的宿主/格式、坏 JSON、无时区时间等。明确报错并停止，不能伪装成 empty；不输出部分对话冒充完整结果。Python 不可用时同样明确降级为用户提供文本。

回归检查只运行合成 JSONL，不扫描真实会话：

```bash
python3 -B -m unittest discover -s "{skill_dir}/Tools" -p 'test_*.py'
```

### 第三步 · 读出盲区

按上面「五种盲区信号」过一遍，每命中一处都记下证据（哪几句话、什么转折让你看出来的）。然后按「选哪一个」的三条判据，选出 1 个最要紧的盲区。

### 第四步 · 微信读书选章

调 weread skill（`WEREAD_API_KEY` 在环境变量里，格式 `wrk-xxxx`；若没有，提示 `export WEREAD_API_KEY=<key>`）。三步：

1. **搜书**——从盲区里抽 1-2 个核心词当 keyword：

```bash
curl -s -X POST https://i.weread.qq.com/api/agent/gateway \
  -H "Authorization: Bearer $WEREAD_API_KEY" -H "Content-Type: application/json" \
  -d '{"api_name":"/store/search","keyword":"<核心词>","count":8,"skill_version":"1.0.3"}' \
  | jq -r '.results[].books[]?.bookInfo | "\(.bookId)\t\(.title)\t\(.author)\t评分\(.newRating)"'
```

从返回里挑评分尽量 ≥750（新版评分是 ×100，即 7.5）、且最贴盲区的 1 本，记 bookId。评分不是唯一标准——对症 > 高分，一本 7.4 但正打在盲区上，胜过一本 8.5 但擦边的。

2. **看目录**——挑最对症那 **1 章**，不是整本、不是序章泛泛：

```bash
curl -s -X POST https://i.weread.qq.com/api/agent/gateway \
  -H "Authorization: Bearer $WEREAD_API_KEY" -H "Content-Type: application/json" \
  -d '{"api_name":"/book/chapterinfo","bookId":"<bookId>","skill_version":"1.0.3"}' \
  | jq -r '.chapters[] | select(.level<=2) | "\(.chapterUid)\t[\(.level)] \(.title)\t\(.wordCount)字"'
```

记 chapterUid、章节标题、wordCount。

3. **估时长**——`wordCount / 280`（中文阅读速度）向上圆到 5 的倍数。无 wordCount 就按目录感觉在 15-45 分钟之间估一个；标题带「上篇/下篇」「卷一」这类宏观词，时长再 ×1.5。

4. **构造网页版链接**——微信读书网页阅读器不接受裸 `bookId` / `chapterUid`，必须先编码。用技能自带工具生成：

```bash
bun "{skill_dir}/Tools/WeReadWebUrl.ts" "<bookId>" "<chapterUid>"
```

工具输出形如：

```text
https://weread.qq.com/web/reader/{encodedBookId}k{encodedChapterUid}
```

把输出的完整 URL 写进笔记。不要手拼编码值，也不要把裸 ID 直接塞进 `/web/reader/`。

**兜底**：搜索全空 / 没对症章节 → 选整本相关书，只传 bookId 生成网页版书籍入口：

```bash
bun "{skill_dir}/Tools/WeReadWebUrl.ts" "<bookId>"
```

文里说明为什么没能精准到章。

### 第五步 · 写笔记

获取时间戳：`date +%Y%m%dT%H%M%S` 和 `date "+%Y-%m-%d %a %H:%M"`（时间用当前，不是 target）。

写入 `~/Documents/notes/{时间戳}--盲区-{主题}__blind.org`。org-mode 格式，禁止 markdown 语法。

正文模板：

```org
#+title: 盲区扫描 · {一句话点出这个盲区}
#+date: [YYYY-MM-DD Weekday HH:MM]
#+filetags: :blind:weread:topology:

* 昨天你在想什么
<1-2 段。当天对话的思维地形——哪几件事、绕着哪个核心在转。给证据：哪几句话看出来的。不流水账，抓主线。>

* 照出来的盲区
<挑出的那 1 个盲区。先一句话点破它是哪种（绕开点 / 空转框架 / 单一取景框 / 未检前提 / 相邻空缺）。再 2-3 段说清：它具体长什么样、昨天哪几处暴露了它、为什么你自己看不见。要点到杠杆——补上之后会打开什么。>

* 这一章给你
- 书：《书名》 — 作者
- 章节：<章节标题>
- 时长：约 N 分钟
- 链接：[[https://weread.qq.com/web/reader/ENCODED_BOOKkENCODED_CHAPTER][在微信读书网页版阅读本章]]
- 为什么是它：<3-4 句。把盲区和这一章对上——这章具体讲什么、怎么补这个盲区。不要泛泛说"开阔视野"，要说清这一章的哪个东西正对这个盲区的哪个缺口。>
```

报告文件路径给用户。

---

## 语气规则（写笔记时守住）

这篇笔记是写给一个跟你长期一起思考的人的，不是报告，不是陌生读者。

- **中文写作，禁翻译腔**。少用「然而 / 此外 / 值得注意的是」；少用名词化（「对…的理解」→「懂…」，「做出…的决定」→「决定」）；主语能省则省；短句优先。写完默念一遍，问：一个没读过翻译小说的中国人会这么说吗？汪曾祺会这么写吗？卡的地方整段重写，不是换个词。
- **禁切痕风金属比喻**。不写「这一刀」「再狠一层」「锋利的话」「砸实」「钉死」「硬话」这一整套自夸元修辞。盲区照得准不准，读者看得出，不用作者吆喝力度。
- **有温度、有毛刺、有判断**。可以有立场，别装中立到虚伪；但标清楚这是判断，不是客观事实。

## org 严格语法（禁混 markdown）

- 标题用 `*` / `**` / `***`，不要 `#`
- 加粗 `*字*`，斜体 `/字/`，等宽 `~code~`
- 列表用 `-`，不要 `*`（`*` 在 org 是标题）
- 链接 `[[url][text]]`，不要 `[text](url)`
- 分隔线 `-----`，不要 `---`；不要 markdown 的 `>` 引用

## 自检（写完前过一遍）

- 盲区有具体证据吗？每一处都能指到昨天哪几句话？没有就退回第三步。
- 只选了 1 个盲区、说透了吗？还是贪多点了三四个？
- 章节链接以 `https://weread.qq.com/web/reader/` 开头，并由工具用非空 bookId、chapterUid 生成？
- 全文没有残留只能唤起移动 App 的专用协议链接？
- 翻译腔查了吗？名词化、「是…的」句、可省的连词，扫一遍。
- 切痕风金属比喻查了吗？「这一刀」「钉死」「砸实」一个不留。
- 三段都有内容、不空段？

## Gotchas

- **网页版 reader 路径使用编码 ID。** `https://weread.qq.com/web/reader/573976?chapterUid=13` 会返回 404；必须用 `Tools/WeReadWebUrl.ts` 分别编码 bookId 与 chapterUid，再用 `k` 连接。
- **章节定位不放在 query 参数。** 正确形态是 `/web/reader/{encodedBookId}k{encodedChapterUid}`；省掉章节编码只会打开整本书入口。

## 和「早信」的分工

Pulse 每天早上有个自动早信（`陈平安思维拓扑.org`），是陈平安的口气、每天一封、挑一个洞。ljg-blind 是**随手调**的分析版——同一套「读昨天 → 看盲区 → weread 选章」的底子，但更系统、专照盲区、分析写得更足，而且能扫任意一天（传日期参数）。想要一封信，等早信；想主动查某天的盲区、要一篇能存档的分析，用 ljg-blind。
