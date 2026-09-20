# BIZ-20260920-02：公式树 V3 离线草稿四项审查修复

- 状态：`APPROVED_OFFLINE_FORMULA_FIX`
- 日期：2026-09-20
- 来源需求：[REQ-20260902-01](REQ-20260902-01-rule-contract-v3-agent2-ready-handoff.md)
- 被替代草稿：`REPORT_RELEASE_ALL_001@20260920T085100000000Z-e04a686188f6-fe1a673845af`
  （[generated-rules/report-release-v3-formula-20260920/](../generated-rules/report-release-v3-formula-20260920/README.md) 保留于磁盘，不得再当作待落库身份）
- 不替代已落库版本：`REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a`

## 四项修复（全部已改）

1. 任务单金额改为 `task.task_amount`，`grain=task`，键 `taskId`。
2. R6 盖章采用建模 A：订单级 `order.in_scope_contract_count` 与
   `order.unsealed_in_scope_contract_count`；五分支只写在计数的 queryRequirements/描述中；
   R6 when 不直接 compare 单合同字段；范围内 count=0 则条件 B 失败。
3. 从确认目录与 FBR 移除 `runtime.current_date` 与规则 cutoff 事实。R4/会签用 date 字面量；
   R8 用表达式 `kind=today`。禁止 `entityType=evaluation`。
4. 产品属性改为 `task.product_id`、`task.product_type_code`，`grain=task`，键 `taskId`。

## 授权边界

本裁决只授权离线修复草稿。未写入 MongoDB，未改 SqlBot，未连接 SQL Server，未调用 DeepSeek。
