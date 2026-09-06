# BIZ-20260906-01：V3 16 项 blocking 业务确认裁决

- 状态：`APPROVED_CONFIRMATION_RECORDED`
- 日期：2026-09-06
- 来源需求：[REQ-20260905-02](REQ-20260905-02-v3-agent2-handoff-readiness.md)
- 关联缺陷：[BUG-20260905-02](BUG-20260905-02-v3-agent2-readiness-blockers.md)
- 被替代决策：无；本决策延续 [BIZ-20260905-02](BIZ-20260905-02-v3-agent2-handoff-contract.md)
  的路径 B 与 [BIZ-20260902-01](BIZ-20260902-01-rule-v3-agent2-ready-boundary.md) 的确认边界。

## 裁决

用户于 2026-09-06 对 [BUG-20260905-02](BUG-20260905-02-v3-agent2-readiness-blockers.md) 的
16 项 blocking 逐类裁决如下：

1. **12 项 `BUSINESS_FACT_MISSING`**：确认以《项目报告和原始数据释放优化方案》现行 V2.0
   语义作为缺失事实的业务确认契约（状态表前提、R0–R9 金额/来源/产品/时间/协议分支、合并报告
   约束与 OA 排除），由工程据此离线补全确认目录。
2. **`task.status_code` 值域冲突**：补录 `19`（内部完工确认）到已确认值域，以规则为准。
   XLSX 字段清单 G 列描述本身写明"主释放任务要求 19"，与本裁决一致；L 列 46 个状态编码
   （226–1042）保持不变。
3. **线下释放/批量释放标志编码冲突**：以 XLSX 确认值域 `{4, 5}` 为准，含义取自 XLSX L 列
   原文"4是5否"（4=是：已线下释放/已标记批量释放；5=否）。现行视图 SQL 使用 0/1 比较的差异
   如实记录为裁决依据；语义（是→已释放/直接释放）不变，物理绑定复核留待导出阶段。
4. **`report.availability.other` 不可达分支**：空值=待定，保留分支；报告/质控报告标志为空时
   进入"等待满足条件"，与方案 V2.0 行为一致。

## 授权边界

本裁决只授权离线重建确认目录与候选（生成新 digest）并重推 readiness 门禁。以下仍需单独授权，
当前数量保持为 0：

- 完整 `RuleParseResultV3`（含测试案例与 query requirements，Slice 3-6）；
- `FactBindingRequest 3.0.0` 真实导出与 MongoDB Schema v5 落库；
- 任何 MongoDB 写入、DeepSeek 调用、SQL Server 访问或 SqlBot 修改。

## 证据

- XLSX 字段清单 L8（46 个任务状态编码）、G8（"主释放任务要求 19"）、L22/L23（"4是5否"）、
  L17/L24（"0有1无"）；workbook SHA-256
  `872706f07792a618888a13d8944d7c59f454e5554388fa2dece511abebb30242`。
- 优化方案固定于私有 bundle（SHA-256
  `c049af189fc3689bac8e96408d9e7239a8c70b66bbcd15829e509c6d524b648f`），其 1.3 节有序规则为
  V3 权威结构来源（用户 2026-09-05 指定）。
- 确认后产物写入 `RuleDataReferences-recovery/report-release-v3-confirmed/`，不含私有正文、
  物理字段、SQL、凭据或本机路径。
