# DEV-20260905-02：V3 Agent 2 交接就绪实现

- 状态：`IMPLEMENTED_HISTORICAL_BLOCKED_STAGE`
- 日期：2026-09-05
- 来源需求：[REQ-20260905-02](REQ-20260905-02-v3-agent2-handoff-readiness.md)
- 决策：[BIZ-20260905-02](BIZ-20260905-02-v3-agent2-handoff-contract.md)

## 等价性与缺口报告

`readiness_v3.py` 固定五个 V2/V3 等价门禁：source identity、stage order、priority、multi-outcome、
postGate/exclusion。当前五项均 fail，路径固定 B。

同一模块把 candidate blocking issue 与引用它的 stage/rule 连接，输出 owner、缺失逻辑事实和 source/
enum/type/entity/parameter/null/filter/aggregation/time 维度。当前分类固定为：

- `BUSINESS_FACT_MISSING`：12；
- `SOURCE_VALUE_CONFLICT`：3；
- `SOURCE_BRANCH_UNREACHABLE_WITH_CONFIRMED_ENUM`：1。

16 条 readiness gate 中 provenance 与不可执行状态通过，其余失败或被 blocking 阻止。因此不得调用
exporter，计划 RuleParseResultV3 与 handoff 数均为 0。

## RuleParseResultV3 设计

业务确认完成后的完整结果必须包含：

- `schemaVersion=3.0.0`；
- `ruleVersion=<ruleSetId>@<UTC timestamp>-<sourceSha12>-<catalogDigest12>`；
- `generatedAt/status=draft/executable=false`；
- 完整 source、Parser/Prompt、catalog、candidate 和测试案例；
- 测试案例覆盖稳定 ruleCode/conditionId、优先级分支、所有 outcome、postGate 和 exclusion；
- `agent2Readiness=ready` 只有 16 条门禁全部通过时成立。

当前不生成该对象，避免把 blocked candidate 冒充完整版本。

## FactBindingRequest 3.0.0

`bindings_v3.py` 定义独立契约，静态 Schema 为
`contracts/fact-binding-request-3.0.0.schema.json`。它复用受控基础类型，但原生增加 V3 ruleRef、
stage/rule/priority/condition/outcome usage 和顶层 evidence；query requirements 不允许 unresolved 模式，
uncertainty 只允许 warning，derived fact 在类型层拒绝。

每个 request ID 固定为 `<ruleVersion>#<factCode>`，result 固定 `fact_value/scalar`，目标固定 SQL Server、
需要 metadata snapshot、禁止 temp table。Pydantic 校验内部字段引用和 evidence 闭包。

## 未来 MongoDB 计划

计划 Schema v5：

- `rule_versions_v3`：一个完整 V3 ruleVersion 一个不可变文档；
- `fact_binding_handoff_batches_v3`：一个 ruleVersion 的全部 request wrapper 保存为一个不可变 batch
  文档，利用 MongoDB 单文档 insert 保证不会留下部分 batch；
- wrapper 仍包含 request ID、ruleVersion、factCode、contractVersion、canonical payload hash、带时区
  createdAt 和完整 camelCase payload；
- 同 ID 同 hash 幂等，异 hash 冲突；写入前全批验证，写入后全批回读并核对数量/身份/hash；
- `rule_structure_candidates_v3` 只读，不 update/replace/delete。

本任务没有实现或执行 migration。具体计划产物由 `analyze_v3_agent2_readiness.py` 离线生成。

## 2026-09-06 后续状态

本文保留业务确认前的 blocked 门禁设计。16 项 blocking 后续已由
[BIZ-20260906-01](BIZ-20260906-01-v3-blocker-business-confirmation.md) 裁决；完整
`RuleParseResultV3`、`FactBindingRequest 3.0.0` 和 ready=true 报告按
[DEV-20260906-01](DEV-20260906-01-rule-parse-result-v3.md) 完成。Schema v5 仍仅为计划，尚未实现或执行。
