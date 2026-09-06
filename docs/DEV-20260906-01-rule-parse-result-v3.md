# DEV-20260906-01：RuleParseResultV3 与 FactBindingRequest 3.0.0 导出器实现

- 状态：`IMPLEMENTED_OFFLINE`
- 日期：2026-09-06
- 来源需求：[REQ-20260905-02](REQ-20260905-02-v3-agent2-handoff-readiness.md)
- 决策：[BIZ-20260905-02](BIZ-20260905-02-v3-agent2-handoff-contract.md)、
  [BIZ-20260906-01](BIZ-20260906-01-v3-blocker-business-confirmation.md)
- 前置设计：[DEV-20260905-02](DEV-20260905-02-v3-agent2-handoff-readiness.md)

## RuleParseResultV3（`result_v3.py`）

- `schemaVersion=3.0.0`、`ruleVersion=<ruleSetId>@<UTC compact timestamp>-<sourceSha12>-<catalogDigest12>`、
  `generatedAt`（带时区）、`status=draft`、`executable=false`。
- `source`：有序规则块溯源（sourceName、relativePath、SHA-256 `f285643e...`、1,402 字符、
  parser/prompt/provider/model）；provider 固定 `reviewed_import`。
- `catalogRef` 与 `candidateRef`：catalog digest 闭包与候选 canonical payload SHA-256
  （sorted-key 紧凑 camelCase JSON，Unicode 保留，禁 NaN）。
- `factDeclarations[]`：每个 required fact 一条声明 = `BindableFactV3` + `QueryRequirementsV3`
  （直接复用 FBR 3.0.0 查询模型，导出 1:1 映射）；`factKind` 逐个指派（本次 16 source、
  1 aggregate、1 exists、0 derived）；查询要求为纯逻辑层，`mappingCandidate` 保持 unresolved，
  物理 relation/column/join 由 SqlBot metadataReview 解析。
- `testCases[]`：`given` + 期望 outcome/reasonCode/matchedRules，由
  `evaluate_rule_structure_v3` 确定性执行；覆盖全部 7 个 outcome、资格阶段首个命中优先级、
  postGate 降级、exclusion 命中与 stateGuards 终态跳过。
- `agent2ReadinessReady`：仅当 16 条门禁全部 pass 时由工厂置 true；导出器对 false 显式拒绝。

## 导出器（`export_fact_binding_requests_v3`）

- 前置拒绝：candidate 有 blocking issue、readiness 非 ready、声明含 derived fact。
- 每个非派生事实一个请求：`requestId=<ruleVersion>#<factCode>`；usage 从 candidate 条件树
  派生（stage/rule/priority/conditionId/path/outcome）；examples 从测试案例中该事实的取值
  派生（去重）；evidence 闭包覆盖声明/查询/usage/示例；uncertainty 仅 warning（标志位 0/1
  与 4/5 编码差异、订单来源值域待补充），逐事实复制。
- 目标固定 sqlserver、需要 metadata snapshot、禁止 temp table。

## readiness 全量推导

`build_agent2_readiness_report_v3` 增加可选 `result`/`requests` 参数：为 None 时行为与证据
文案逐字节不变（历史产物可复现）；提供 result 后 gate 1/4/5/7-12 改按 result 与导出闭包
判定，全部 pass 时 `ready=true`。

生成流程为两阶段：先以 `agent2ReadinessReady=false` 构建 result 并验证除 gate 4 外全部
pass（gate 4 为 blocked），随后置 ready 标志、执行导出（导出器对非 ready 显式拒绝），最后
以 result+requests 重推 16 条门禁，全部 pass 才写产物；任一环节失败即 fail-fast。

## 边界

本切片只生成离线、不可执行、待审核产物；不实现或执行 Schema v5 migration，不写 MongoDB，
不调用 DeepSeek，不访问 SQL Server，不修改 SqlBot。规则版本时间戳由显式参数固定以保证
产物可复现。
