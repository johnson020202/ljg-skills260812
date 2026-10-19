# ValidateClassic

复核 classic JSON、PNG 与 manifest 是否仍保持同一份输入、尺寸、哈希和 DOM 审计结果。

```bash
bun Tools/ValidateClassic.ts \
  --input <classic.json> \
  --png <classic.png> \
  --manifest <classic.manifest.json>
```

三个参数均必填。成功时 stdout 返回 JSON `status: "valid"`；任一底本、token、覆盖率、尺寸、哈希、顶部配图 presence/visibility 或必需区块可见性不一致时非零退出。运行 `bun Tools/ValidateClassic.ts --help` 查看当前参数。

只接受完整的 `schemaVersion: 2`。`dom.originalMatches`、完整 `dom.fontSizes`、`qaSliceDetails`（没有切片时为 `[]`）及其余渲染器字段都是必填；删除字段不会进入 legacy 模式，HTML 必须与当前确定性渲染结果完全一致。旧的缺字段 manifest 需要重新渲染，本工具不提供隐式 legacy 兼容。

覆盖率由实际正文字符与注解重新计算，不能用 `punctuation: true` 隐藏正文。主 PNG、QA 切片和 hero 都受图片资源预算与真实解码检查；通过哈希不代表图片可解码。manifest 仍是文件组一致性证据，不是浏览器渲染过程的数字签名或视觉正确性证明。
