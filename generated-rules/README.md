# generated-rules — JSON 规则生成归档

本文件夹用于记录 RuleReader JSON 规则的生成产物与 MongoDB 落库实况。所有内容均为**待审核的
不可执行草稿**（`executable=false`、`status=draft/blocked`），不代表已发布或可执行的正式业务规则。

创建时间：2026-09-06。当日真实 Agent 1（DeepSeek）生成尝试 5 次运行、21 次调用全部被门禁拒绝，
没有产出任何模型生成的 JSON（见
[BUG-20260906-05](../docs/BUG-20260906-05-agent1-v2-real-call-convergence-blocker.md)）；因此本文件夹
当前收录的是经用户授权的 reviewed_import 确认产物与 MongoDB 实况快照，不含任何伪造数据。

## 目录

| 子目录 | 内容 | 来源与验证 |
| --- | --- | --- |
| `report-release-v3-confirmed/` | 《项目报告释放规则》V3 确认交付：19 事实确认目录、19 节点全 active 候选、`RuleParseResultV3`（18 事实声明 + 20 测试案例）、18 条 `FactBindingRequest 3.0.0`、16/16 pass 的 Agent 2 readiness 报告、确认恢复 manifest | 字节级复制自 `RuleDataReferences-recovery/report-release-v3-confirmed/`（2026-09-06 13:57 再生产物）。六个文件 SHA-256 与 manifest 记录逐一比对 **全部一致**；manifest 自身 SHA-256 `0ef3af69…` 等于 `scripts/persist_report_release_v3_delivery.py` 冻结的批准信任锚，可直接作为该脚本的 `--artifact-dir` 输入。业务裁决依据见 [BIZ-20260906-01](../docs/BIZ-20260906-01-v3-blocker-business-confirmation.md) 与 [BIZ-20260906-02](../docs/BIZ-20260906-02-v3-mongodb-persistence.md)。 |
| `report-release-v3-recovery-20260905/` | 2026-09-05 V3 MongoDB 恢复（Schema v4）产物：7 事实目录（catalog digest `f2bf1c99…`）、19 节点候选（3 active / 16 blocked）、恢复 manifest | 复制自 `RuleDataReferences-recovery/report-release-v3/`。catalog/candidate 文件 SHA-256 与 `recovery-manifest.json` 记录比对 **一致**。当日该候选曾持久化到旧实例的 `rule_structure_candidates_v3`（1 条），随容器重建丢失，此处为唯一完整存档。状态为 `validatedBlockedCandidate`，16 项 blocking 已由 [BIZ-20260906-01](../docs/BIZ-20260906-01-v3-blocker-business-confirmation.md) 裁决关闭（关闭结果体现在 confirmed 目录）。 |
| `mongodb-snapshot-20260906/` | 2026-09-06 晚当前 MongoDB `rule_reader` 库的**全量导出**（全部集合、全部文档） | 快照脚本导出，共 5 条文档：1 条 `app_metadata`（Schema v4，service 0.12.0）+ 4 条 `schema_migrations`（v1-v4）。三个业务集合 `rule_versions`、`fact_binding_handoffs`、`rule_structure_candidates_v3` 均为 **0 条**——容器当日重建后历史记录（2 条规则、33 条交接、1 条 V3 recovery）不在当前实例。凭据不写入快照。 |

## 安全说明

- 两个 JSON 产物目录经扫描确认不含：可执行 SQL 文本、数据库连接串、凭据模式、本机绝对路径、
  私有仓库路径。规则描述、XLSX 确认单元格原文与视图溯源名属于既有已接受产物的同级别内容。
- 本文件夹已按用户授权纳入版本控制（2026-09-06）。
- 任何向真实 MongoDB 的持久化仍需用户单独授权（写入脚本见
  `scripts/persist_report_release_v3_delivery.py`，运行时数据库默认 Schema v4，仅该脚本显式请求 v5）。
