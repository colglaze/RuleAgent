# REQ-20260905-02：V3 Agent 2 交接就绪门禁

- 状态：`COMPLETED_OFFLINE_READY`
- 日期：2026-09-05
- 来源：用户要求修复当前无 SqlBot 可消费规则与事实交接的问题；本任务禁止写 MongoDB、调用模型、
  生成 SQL 或修改 SqlBot。
- 前置需求：[REQ-20260902-01](REQ-20260902-01-rule-contract-v3-agent2-ready-handoff.md)
- 决策：[BIZ-20260905-02](BIZ-20260905-02-v3-agent2-handoff-contract.md)
- 初始门禁设计：[DEV-20260905-02](DEV-20260905-02-v3-agent2-handoff-readiness.md)
- 完成决策：[BIZ-20260906-01](BIZ-20260906-01-v3-blocker-business-confirmation.md)
- 完成设计：[DEV-20260906-01](DEV-20260906-01-rule-parse-result-v3.md)

## 结论范围

本切片先执行 V2/V3 语义等价性门禁、16 项 blocking 分类和 16 条 Agent 2 readiness 检查。任一业务
blocking 存在时，输出规则版本数和 handoff 数必须均为 0，只生成不可执行的确认清单与落库计划。

## 验收标准

- 通过源码契约和来源 SHA-256 确定性选择路径 A/B，不因旧 exporter 存在而恢复 V2。
- blocking 报告保留全部 issue，包含 code、阶段、规则、owner、逻辑事实和各语义维度；不得包含私有
  正文、物理字段或 SQL。
- readiness 逐项覆盖规则版本、blocking、事实闭包、query requirements、condition usage、证据和
  provenance。
- 路径 B 冻结 `FactBindingRequest 3.0.0` 的 Pydantic 与 Draft 2020-12 Schema；blocking 载荷被拒绝。
- 当前不生成 RuleParseResultV3 或 handoff；落库计划明确未来数量、版本、hash、migration、索引、
  幂等、冲突、原子批次和回读策略。
- 默认测试离线；本任务不读写 MongoDB，不调用 DeepSeek/SQL Server，不修改 SqlBot。

## 2026-09-06 后续完成

用户完成 16 项业务确认并另行授权 Slice 3-6 后，本需求已生成一个待审核、不可执行的
`RuleParseResultV3`、18 条 `FactBindingRequest 3.0.0` 和完整 readiness 报告；16 条门禁全部通过，
`ready=true`。初始阶段“有 blocking 时输出为 0”的验收规则仍保留并由回归测试覆盖。

MongoDB Schema v5 持久化与 SqlBot 的 3.0.0 intake 仍是各自独立的后续任务。
