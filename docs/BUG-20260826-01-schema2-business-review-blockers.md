# BUG-20260826-01：Schema 2.0 草稿业务审核仍有事实与映射阻断

- 状态：`REMEDIATED_IN_UNPERSISTED_DRAFT_AWAITING_REVIEW`
- 日期：2026-08-26
- 来源 REQ：[REQ-20260819-01](REQ-20260819-01-rule-contract-v2-agent2-handoff.md)
- 修订 REQ：[REQ-20260827-01](REQ-20260827-01-schema2-business-review-remediation.md)
- 修订 DEV：[DEV-20260827-01](DEV-20260827-01-schema2-business-review-remediation.md)
- 发现于：[BIZ-20260826-01](BIZ-20260826-01-schema2-draft-business-review.md)
- 关联缺陷：[BUG-20260819-01](BUG-20260819-01-rule-ast-semantic-loss.md)
- 影响版本：应用 `0.8.0`、规则 Schema `2.0.0`
- 影响草稿：`REPORT_RELEASE_ALL_001@20260824T080726492666Z-562eabd40e5a`
- 修订草稿：`REPORT_RELEASE_ALL_001@20260827T013225952760Z-562eabd40e5a`（仅本地导出、未持久化）

## 1. 现象

Schema `2.0.0` 草稿已经修复历史版本的公式和分支 AST 丢失，但业务审核发现该精确版本仍不能批准：

1. 多个事实把规则求值实体 `formal_test_task` 与事实自身的业务粒度混为一谈。14 个订单范围事实或派生事实仍声明 `grain=formal_test_task`；合并报告级、合并报告订单级和运行时日期事实也存在类似问题。
2. `workflow.has_unfinished_report_release` 与 `release.special_application_approved` 的来源按任务号 `sqlc` 关联，草稿却统一声明数值型 `taskId`，没有证据证明两个业务键等价。
3. 6 个金额/费用事实不能继续使用当前辅助视图候选：`amount.receipts_total`、`amount.deposit_amount` 依赖定义缺失的 `v_sto`，其余 4 个费用字段与主视图的状态相关数量回退口径不同。
4. `report.merge_flag.allowedValues=[0,1]`，但来源明确存在“其他值”，草稿案例 `merge-deduplication-fail` 自身使用值 `2`。
5. 当前校验只验证案例引用和最终解释结果，不校验 `given` 是否满足事实的 `dataType/allowedValues/nullable`，因此第 4 项未被门禁发现。
6. 20 个案例虽全部得到声明结果，但有 15 个条件节点从未同时覆盖通过和失败；来源中的非框架单位属性 `14` 合同路径没有实际通过对应 AST 分支。

## 2. 业务影响

- 该草稿仍为 `draft` 且不可执行，没有生产规则执行影响。
- 33 条事实交接均已有 `blocking` 不确定性，当前没有进入 SqlBot 候选生成。
- 如果未来仅解除下游字段/筛选阻断而不先修复本缺陷，SqlBot 可能把错误粒度或辅助视图费用口径当成已声明业务语义。
- 当前版本、历史 V1 草稿及既有交接记录均不可覆盖或删除。

## 3. 可重复证据

- 来源规范化 SHA-256：`562eabd40e5a5701fb9515499b542a6e2ff46056464621b1abb0a7c37f116e4d`。
- 精确规则导出 SHA-256：`993a527f94fb38281d9804cee3f507c9b25cdcaf7600e1af50df805f3ff57fdd`。
- 结构计数：41 个事实（17 `source`、12 `aggregate`、4 `exists`、8 `derived`），65 个条件（13 `all`、9 `any`、1 `not`、42 `compare`），20 个案例，8 个候选映射。
- `reviewed_import` profile 经可信 enrichment 后与精确导出规则正文完全一致。
- 离线逐案例值域复核唯一确定冲突为：`merge-deduplication-fail` 提供 `report.merge_flag=2`，事实允许值为 `[0,1]`。
- 离线条件覆盖复核得到 15 个单侧节点，完整清单见 [BIZ-20260826-01](BIZ-20260826-01-schema2-draft-business-review.md#5-20-个案例审核)。
- 候选映射差异来自来源明确区分的两套数量口径：主视图按任务状态决定空完成数量的回退，`v_OrderFormaltestsettlement` / `v_ReportDataReleaseRules` 辅助口径在完成数量为空时直接使用下单数量。

## 4. 临时约束

- 本 V2 草稿业务审核结论为未批准；不得发布、执行或作为已确认事实绑定来源。
- 现有 33 条 `fact_binding_handoffs` 只可保留和只读审计，不得补丁、覆盖或删除。
- 6 个被拒绝的金额/费用映射不得在下游解释为已审核 Provider。
- 不通过恢复 `FactBindingRequest 1.0.0`、猜测字段或忽略 `blocking` 来绕过问题。
- 本 BUG 不授权持久化新草稿、调用 DeepSeek、实现 SqlBot 或生成 SQL。

## 5. 修复验收

1. 先在后续独立任务中更新对应 REQ/DEV，明确事实粒度与参数角色；复杂修订不得直接改脚本后持久化。
2. 逐项修正或确认 41 个事实，至少覆盖订单级事实、合并报告级事实、任务号关联和运行时日期。
3. 6 个错误金额/费用候选必须改为 `unresolved` 或替换为与主视图口径完全一致且可复核的来源。
4. `report.merge_flag` 的值域与来源及案例一致；确定性校验新增案例输入的类型、可空性和允许值校验，并保留回归测试。
5. 新案例覆盖本次发现的 15 个单侧条件节点，并保留来源文档已有案例语义。
6. 修订候选重新通过 Pydantic、语义闭包、确定性解释器、专项审计、事实请求 Pydantic/JSON Schema 和安全门禁。
7. 修复只能产生新的不可变 `ruleVersion`，仍为 `draft`、`executable=false`；是否持久化必须由用户单独明确授权。
8. 修复前后历史 V1、本次 V2 和现有 `fact_binding_handoffs` 的 BSON/载荷保持不变。
9. 默认测试不调用真实 DeepSeek、网络、MongoDB 或 SQL Server；Ruff、严格 Mypy 和受影响离线测试通过。

## 6. 范围外

- 当前草稿原地修改、批准、发布或执行；
- RuleReader 内实现 Agent 2、元数据发现、SQL 生成或 SQL 执行；
- 修改 SqlBot 或 RuleReader 所有的不可变交接集合。

## 7. 2026-08-27 修复结果

- 新 profile 冻结订单、合并报告、合并报告订单、任务和规则求值粒度，并区分 `taskId`、`taskNumber`、`orderId`、`mergeReportId` 与 `evaluationDate`。
- 原复合事实拆为 `task.raw_data_flag` 和 `release.has_approved_raw_data_record`，原始数据直接路径改为显式双条件 `all`。
- `report.merge_flag` 不再限制未被来源封闭的值；案例输入现在先经过 `dataType/nullable/allowedValues` 门禁。
- 6 个不能证明等价的金额/费用映射均恢复为 `unresolved`，仅保留 `order.amount` 与 `contract.current_order_meet_flag` 两个候选。
- 修订版包含 42 个事实、67 个条件和 31 个案例；所有 67 个节点均得到至少一次 `pass` 和一次 `fail`。
- 新规则及 34 条事实请求已离线导出并通过全部契约和安全门禁，34 条请求全部保持 blocking。

该状态表示 BUG 的技术修订已在新的未持久化草稿中实现。旧受影响版本没有修补，且新草稿尚未完成业务复审，因此不能将本 BUG 解释为业务批准、持久化授权或可执行状态。
