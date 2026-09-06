# REQ-20260905-01：V3 候选恢复到 MongoDB

- 状态：`IMPLEMENTED`
- 日期：2026-09-05
- 来源：用户明确要求把换机恢复的 V3 数据写入当前电脑 MongoDB。
- 前置需求：[REQ-20260902-01](REQ-20260902-01-rule-contract-v3-agent2-ready-handoff.md)
- 决策：[BIZ-20260905-01](BIZ-20260905-01-v3-candidate-mongodb-boundary.md)
- 设计：[DEV-20260905-01](DEV-20260905-01-v3-candidate-mongodb-recovery.md)

## 目标

把已通过 V3 catalog/candidate 确定性门禁、固定到私有 bundle 和有序规则块的恢复结果，以不可变、
幂等、可精确回读的候选记录保存到当前 `rule_reader` MongoDB。

## 验收标准

- MongoDB Schema v4 新增独立 `rule_structure_candidates_v3`，不混入 V1/V2 `rule_versions`。
- 保存完整 `BusinessConfirmedFactCatalogV3`、`RuleStructureCandidateV3`、固定来源身份和 canonical
  payload SHA-256。
- `_id/candidateId` 由 ruleSetId、规则块哈希和 catalog digest 确定性生成；同 ID 同 payload 幂等，
  不同 payload 冲突且不覆盖。
- 写入前后都重新执行 V3 Pydantic、catalog digest、候选语义、来源身份和 payload hash 校验。
- 记录固定为 `validatedBlockedCandidate`、`executable=false`；16 个 blocking 原样保留。
- CLI 必须显式提供私有 reference root；不调用 DeepSeek、SqlBot 或 SQL，不生成
  `FactBindingRequest`，不修改 `rule_versions/fact_binding_handoffs`。
