# BIZ-20260905-01：V3 MongoDB 候选恢复边界

- 状态：`APPROVED`
- 日期：2026-09-05
- 来源需求：[REQ-20260905-01](REQ-20260905-01-v3-mongodb-recovery.md)

## 决策

1. 当前 V3 只有事实目录和规则结构候选，不是完整 `RuleParseResultV3`；不得写入现有
   `rule_versions`，避免破坏 V1/V2 回读和 SqlBot 最新规则接口。
2. 新集合 `rule_structure_candidates_v3` 只保存不可执行候选恢复记录，由 RuleReader 唯一写入；没有
   运行时或 SqlBot consumer。
3. catalog 和 candidate 必须一起保存并绑定私有 bundle、XLSX、有序规则块哈希；不能只写其中一项。
4. blocking 候选允许归档以支持换机恢复和审计，但不得标记为已批准、发布、可执行或可交接。
5. 本任务不创建 V3 事实交接，不把 V3 数据转换为 `FactBindingRequest 2.0.0`，也不修改历史 MongoDB
   规则和事实记录。
6. 私有来源正文、视图 SQL、XLSX 原始字节和凭据不进入 MongoDB；只保存经过契约约束的 catalog、
   candidate 和固定哈希。
