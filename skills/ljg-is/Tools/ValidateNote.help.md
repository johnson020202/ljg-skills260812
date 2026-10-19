# ValidateNote

校验 `ljg-is` 生成的 Org 或 Markdown 笔记。无 schema 的历史笔记继续按 v1 六段结构验收；带 `schema: ljg-is-v2` 的新笔记按七段结构验收，并检查「结构迁移」中的结构式、变量映射、远域迁移与边界。

v2 一级标题严格依次为：`问题 / 完整表达 / 剥离 / 本质 / 示例 / 结构迁移 / 验证`。其中「结构迁移」严格使用四个强调 bullet：`结构式 / 变量 / 迁移 / 边界`。

```bash
bun "{skill_dir}/Tools/ValidateNote.ts" \
  ~/Documents/notes/20260801T010203--本质-taxi__is.org
```

成功时向 stdout 输出 `{"status":"ok", ...}` 并退出 0；失败时向 stderr 输出错误数组并退出 1。缺少文件参数时退出 2。

`{skill_dir}` 替换为本次实际加载的 `ljg-is/SKILL.md` 所在绝对目录；适用于项目级、全局和插件安装，不回退执行另一份副本。

Markdown 必须以 `---` 开始，以 `---` 或 `...` 结束 YAML frontmatter；使用 Bun 内建 `Bun.YAML.parse`（已验证 Bun 1.3.14）。字符串引号、行内/块标签数组均支持；也兼容字符串形式的 tags。Org 仍使用同一行非空的 `#+` 字段。无 schema 才走 legacy；空值或错误类型不会静默降级。占位符检查同时覆盖正文和解析后的元数据字符串（含嵌套对象/数组），YAML 注释不参与正文或元数据检查。

运行自检：

```bash
bun test "{skill_dir}/Tools/ValidateNote.test.ts"
```
