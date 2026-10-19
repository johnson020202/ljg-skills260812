# RenderClassic

把 classic JSON 渲染为完整 HTML、单张 PNG、manifest，并可生成重叠视觉验收切片。

```bash
bun Tools/RenderClassic.ts \
  --input <classic.json> \
  --output <classic.png> \
  --html <classic.html> \
  --width 1080 \
  --slices-dir <qa-slices>
```

`--input` 与 `--output` 必填。`--width` 接受 720–1600；默认 1080。省略 `--html` 时写到 PNG 同目录同名 HTML。运行 `bun Tools/RenderClassic.ts --help` 查看当前参数。

输入 JSON 可选填成对的 `heroImage` 与 `heroAlt`。`heroImage` 只接受相对 JSON 或绝对路径的本地 PNG/JPEG/WebP；渲染器会把它编码进 HTML，不保留文件热链。

渲染前会校验原文逐字回读、非标点注解覆盖、tone 枚举、顶部配图和章节解读禁词；渲染后会检查页面溢出、裁切、空文本、配图可见性、必需标题与真实 PNG 解码。

输入、hero、HTML、PNG、派生 manifest 与切片目录必须互不重叠。写入前检查真实路径、符号链接祖先、硬链接、大小写及 Unicode 归一别名；切片目录不得包含输入或其他主产物。输出文件符号链接及与生成切片名冲突的未受管文件会被拒绝。正常输入/hero 的非冲突本地符号链接可以读取。

产物先在目标文件系统的临时目录生成，全部完成后才替换；提交中途失败会恢复原文件组。成功重跑仅替换形如 `01--y-0.png` 的生成切片，保留其他文件。跨文件提交不是面向并发读者的原子快照；进程被强杀或断电时可能留下 `.classic-stage-*` 恢复目录，不要直接删除其中的旧产物备份。

图片预算为每文件最大 32 MiB、3200 万像素、单边 32768 像素，渲染截图前同样检查像素预算。PNG 保留容器边界/CRC 校验，并由锁定的 sharp/libvips 实际解码；PNG/JPEG/WebP 配图也必须可解码，不接受动画。解码设 15 秒操作时限。依赖与锁文件均在本技能内，使用 `bun install --frozen-lockfile --ignore-scripts` 安装；浏览器继续使用 Playwright 的匹配 Chromium。
