# BUG-20260903-01：V3 确认与校验缺口

- 状态：`RESOLVED_BY_BUSINESS_CONFIRMATION`
- 日期：2026-09-03
- 来源需求：[REQ-20260902-01](REQ-20260902-01-rule-contract-v3-agent2-ready-handoff.md)

历史摘要显示首轮实现曾改写确认目录值、制造不存在的 binding profile，并遗漏来源冲突。修订后的
工程门禁现已固定：catalog digest 必须匹配；无 binding profile 时必须保留 binding issue；active
规则只能引用确认事实；目录外概念必须 proposed + blocked；候选阻断返回 `INDETERMINATE`。

2026-09-05 用户确认私有 XLSX 中已填写数据均已核对有效，只是未更新“核对状态”；同时指定第 1.3
节的有序项目报告规则作为 V3 结构权威。当前可以恢复 source-bound catalog 和候选。XLSX 与有序规则
之间的编码/枚举差异继续作为 blocking source conflict，binding profile 仍未批准；原文不复制进公开
仓库。

2026-09-06 后续关闭：用户已通过
[BIZ-20260906-01](BIZ-20260906-01-v3-blocker-business-confirmation.md) 裁决来源冲突和缺失事实；
确认候选现为 19 个 active、0 blocking。物理 binding profile 仍保持 unresolved，留待 SqlBot 的
元数据绑定阶段处理，不影响 RuleReader 离线 readiness。
