# 优化方案 3.1.0 完全一致交付（2026-09-20 对齐）

唯一待消费的 Schema **3.1.0** 完整交付（项目报告 + 原始数据）。`draft` / `executable=false` /
`purpose=optimization-plan-generation` / mapping unresolved。**已写入本机 MongoDB Schema v6**
（insert-only，未覆盖 2026-09-05 confirmed 版本）。

不得把下列身份当作本任务交付：

- 已落库 `REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a`
- 2026-09-17 的 3.1.0（R4 曾误用「数据释放状态=已释放」）
- 2026-09-20 公式树 3.0.0（`report-release-v3-formula-20260920*`，盖章建模 A 与合并组黑盒）

## 身份

| 项 | 值 |
| --- | --- |
| 权威文件 SHA-256 | `c049af189fc3689bac8e96408d9e7239a8c70b66bbcd15829e509c6d524b648f` |
| parseInputSha256 | `aebdbf4cf89d469ccd2bfc61d9f70aa24d4361e3ed5fb947c1221f8f8676b662` |
| bundle commit | `2240e5bd18e36d17650896a10cc61e1c18e3daa0` |
| 报告 ruleVersion | `REPORT_RELEASE_ALL_001@20260920T131600000000Z-c049af189fc3-6d94836af30f` |
| 报告 catalogDigest | `6d94836af30ff47f969fe779cf19430111977e3d306a0b6ab76a42cd3b5b211b` |
| 报告请求 / 案例 | 33 / 75 |
| 原始数据 ruleVersion | `RAW_DATA_RELEASE_ALL_001@20260920T131600000000Z-c049af189fc3-2845743f259a` |
| 原始数据 catalogDigest | `2845743f259a43ca79f5f08c6e4ae482f12b53bd864388aff068a95efb1211b4` |
| 原始数据请求 / 案例 | 18 / 29 |
| `mongodbWritten` | `true` |

对照表见 [optimization-plan-v31-coverage-matrix.md](../../docs/optimization-plan-v31-coverage-matrix.md)。
裁决见 [BIZ-20260920-03](../../docs/BIZ-20260920-03-optimization-plan-full-alignment.md)。

完成不等于总 SQL 已生成。已按 2026-09-20 用户授权落库；SqlBot intake 仍需另行授权。
