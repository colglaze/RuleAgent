# BUG-20260903-02：Agent 1 V3 单次调用被 Schema 拒绝

- 状态：`HISTORICAL_RECORD_RECONSTRUCTED_ENGINEERING_GUARD_ADDED`
- 日期：2026-09-03
- 来源需求：[REQ-20260902-01](REQ-20260902-01-rule-contract-v3-agent2-ready-handoff.md)

现存摘要记录两次各自授权的单次调用：第一次有 5 处 condition id 格式错误，第二次有 4 处 factCode
格式错误。随后一次有界任务在首个响应发现业务事实缺口并提前停止，且候选存在 ruleCode 重复。
原响应不在仓库，具体字段位置不可复核。

恢复实现对 ID pattern、ruleCode 全局唯一、factCode 确认目录闭包和 1–3 次硬预算建立确定性测试；
业务缺口使用 `BUSINESS_CONFIRMATION_REQUIRED` 非重试终止。该修复不声称历史候选已变为有效。
