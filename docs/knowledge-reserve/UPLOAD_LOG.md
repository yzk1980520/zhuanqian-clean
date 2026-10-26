# 知识储备文档上传日志

- **上传时间**：2026-08-31 02:00 ~ 02:06
- **目标空间**：space_id `7679453930144680918`
- **目标根节点**：https://ccnqd0zqf6u2.feishu.cn/wiki/APZtw84YGiB07XkUl7lcioOrn3c（知识问答）
- **父节点标题**：知识储备·总管联网搜索·20260831
- **父节点 URL**：https://ccnqd0zqf6u2.feishu.cn/wiki/BgMLwvdZ3iPp1Dk4kp6camrJnOg
- **上传方式**：`lark-cli wiki +node-create` 建节点 → `lark-cli docs +update --command overwrite --doc-format markdown` 写入内容

## 上传结果清单

| # | 本地文件 | 飞书 URL | 状态 |
|---|---|---|---|
| 0 | （父节点） | https://ccnqd0zqf6u2.feishu.cn/wiki/BgMLwvdZ3iPp1Dk4kp6camrJnOg | 成功 |
| 1 | A_选股系统增强知识.md | https://ccnqd0zqf6u2.feishu.cn/wiki/U4HAwKM7CiUrI1kNrMvcGlfynIp | 成功 |
| 2 | B_智能体能力提升知识.md | https://ccnqd0zqf6u2.feishu.cn/wiki/OseAwx1Lai4sVmkQvgDcSLp1nyb | 成功 |
| 3 | C_Skill库扩展建议.md | https://ccnqd0zqf6u2.feishu.cn/wiki/IE1iwm5v8iqGlqkReMDcQvCvn4b | 成功 |
| 4 | README.md（汇总索引） | https://ccnqd0zqf6u2.feishu.cn/wiki/T4CDwqKecicWngkAzOnce7JxnAb | 成功 |

## 说明

- 4 个 wiki 子节点全部以 `obj_type=docx` 建出后，用底层 obj_token 通过 `docs +update --command overwrite` 把 Markdown 原文写入；返回 `revision_id=3` 与 `result=success`。
- 飞书在写入 Markdown 时会用 H1 同步节点标题：
  - A 节点最终标题：`方向 A · 选股系统增强知识（针对 zhuanqian）`
  - B 节点最终标题：`方向 B · 智能体（AI Agent）能力提升知识`
  - C 节点最终标题：`方向 C · Skill 库扩展建议`
  - 汇总索引标题：`知识储备 · 汇总索引`
- 节点路径：知识问答 → 知识储备·总管联网搜索·20260831 → {A, B, C, 汇总索引}
- 上传后再次 `wiki +node-list --parent-node-token BgMLwvdZ3iPp1Dk4kp6camrJnOg` 验证：4 个子节点全部存在。

## 待上传

（无）
