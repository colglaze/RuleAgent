# BIZ-20260905-02：V3 Agent 2 交接契约决策

- 状态：`APPROVED_PATH_B`
- 日期：2026-09-05
- 来源需求：[REQ-20260905-02](REQ-20260905-02-v3-agent2-handoff-readiness.md)

## 决策

1. 选择路径 B。V2 remediation 来源 SHA-256 为 `562eabd4...`，当前有序 V3 为 `f285643e...`；V2
   单根 PASS/FAIL AST 无法表达五阶段、首个命中优先级、多 outcome、postGates 和 exclusions，禁止
   将旧 V2 恢复为当前规则。
2. `FactBindingRequest 2.0.0` 的 ruleRef 固定 `schemaVersion=2.0.0`，不能精确引用 V3。因此建立独立
   `FactBindingRequest 3.0.0`；SqlBot 必须通过后续独立 REQ/BIZ/DEV 升级，不静默兼容。
3. 完整 `RuleParseResultV3` 必须包含不可变 ruleVersion、source/catalog/candidate hash 闭包、Parser/
   Prompt provenance、完整测试案例和 Agent 2 readiness 结论。当前 candidate 有 16 个 blocking，不能
   形成该可交接版本。
4. V3 handoff 只导出非 derived 事实；每个请求携带 entity、grain、key parameters、稳定 fields、完整
   filters、aggregation、timeRange、scalar result、stage/rule/condition usage、证据和 provenance。
5. ready handoff 不允许 blocking uncertainty；物理 relation/column/join grant 仍由 SqlBot 的
   metadataReview 管理。
6. 未来 MongoDB 使用独立 `rule_versions_v3` 和单文档原子
   `fact_binding_handoff_batches_v3`，不改变 V1/V2 reader 或当前 `rule_structure_candidates_v3`。
7. 当前任务只生成计划。计划规则数 0、handoff 数 0；不得为了产生 SqlBot 输入删除或降级 blocking。

## 后续状态说明（2026-09-06 补充）

上文第 3、7 条是 2026-09-05 业务确认前的历史状态：当时 candidate 仍有 16 项 blocking，因此
“不能形成可交接版本”和“只生成计划、数量为 0”的结论只对当时有效，原始决策正文保持不改写。
16 项 blocking 已由 [BIZ-20260906-01](BIZ-20260906-01-v3-blocker-business-confirmation.md)
裁决关闭，完整 `RuleParseResultV3` 与 18 条 `FactBindingRequest 3.0.0`（16/16 readiness 全
pass，ready=true）已按 [DEV-20260906-01](DEV-20260906-01-rule-parse-result-v3.md) 离线完成。

第 6 条的独立集合计划已由 [REQ-20260906-01](REQ-20260906-01-v3-mongodb-persistence.md)、
[BIZ-20260906-02](BIZ-20260906-02-v3-mongodb-persistence.md) 和
[DEV-20260906-02](DEV-20260906-02-v3-mongodb-persistence.md) 冻结并实现（MongoDB Schema v5）；
真实写入当前 MongoDB 仍需用户单独授权执行。SqlBot 仍只支持 `2.0.0`，其 `3.0.0` intake 必须在
SqlBot 仓库独立升级，RuleReader 不提供静默兼容。
