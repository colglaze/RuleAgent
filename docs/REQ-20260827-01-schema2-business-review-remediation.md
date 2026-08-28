# REQ-20260827-01：Schema 2.0 草稿业务审核阻断修订

- 状态：`COMPLETED`
- 日期：2026-08-27
- 来源：用户明确授权修复 [BUG-20260826-01](BUG-20260826-01-schema2-business-review-blockers.md)，仅生成未持久化新草稿
- 前置需求：[REQ-20260819-01](REQ-20260819-01-rule-contract-v2-agent2-handoff.md)
- 业务审核：[BIZ-20260826-01](BIZ-20260826-01-schema2-draft-business-review.md)
- 技术方案：[DEV-20260827-01](DEV-20260827-01-schema2-business-review-remediation.md)
- 完成证据：[PROG-20260827](PROG-20260827.md)

## 1. 背景

不可变草稿 `REPORT_RELEASE_ALL_001@20260824T080726492666Z-562eabd40e5a` 已完成业务审核但未获批准。核心条件 AST 与来源一致，阻断集中在事实粒度和业务键、费用候选映射、`report.merge_flag` 值域、复合原始数据条件及案例输入/分支覆盖。

本需求只形成一个新的、未持久化 Schema `2.0.0` 草稿和离线审计产物。旧 V1、当前 V2、正式 `rule_versions` 与 33 条 `fact_binding_handoffs` 必须保持不变。

## 2. 目标

- 保留 2026-08-24 profile 和精确导出作为旧版本复现基线，新增独立修订 profile。
- 把事实自身粒度与规则求值实体分离，冻结订单、合并报告、合并报告订单、任务和规则求值上下文粒度。
- 区分数值型任务 ID 与来源流程关联使用的任务号 `sqlc`。
- 把 `yssj=0 AND approved-record-exists` 从一个复合布尔事实拆成两个事实和显式 `all` 条件。
- 撤销不能证明与主视图口径等价的费用/到款候选映射，只保留可逐字段复核的候选。
- 校验案例输入与事实 `dataType/nullable/allowedValues` 一致，并补足条件双向覆盖。
- 生成新的 Schema `2.0.0`、`draft`、不可执行草稿及 34 条非派生事实请求，但不写 MongoDB。

## 3. 范围内

- 应用版本升级到 `0.9.0`；MongoDB Schema 保持 v3。
- 新增 source-hash-bound 修订 profile 和只允许本地导出的离线脚本。
- `build_reviewed_rule_result` 支持显式 reviewed import 契约版本；旧调用默认仍为 `reviewed-import-v1`，新草稿使用 `reviewed-import-v2`。
- 事实粒度和参数修订：
  - 订单事实使用 `grain=order + orderId`；
  - 合并报告合同事实使用 `grain=merge_report + mergeReportId`；
  - 跨订单失败数使用 `grain=merge_report_order + mergeReportId/orderId`；
  - 流程事实使用字符串 `taskNumber`，对应来源 `sqlc`；
  - 数据库当天日期使用 `grain=rule_evaluation + evaluationDate`，不再依赖 `taskId`。
- 原始数据直接路径拆分为 `task.raw_data_flag` 与 `release.has_approved_raw_data_record`。
- 候选映射只保留：
  - `order.amount -> v_OrderFormaltestsettlement.yhhje`；
  - `contract.current_order_meet_flag -> v_ReportReleaseSealCondition.dd_ismeet`。
- 新增案例输入类型/可空性/允许值校验和对应回归测试。
- 新增隔离案例，使新条件树每个节点至少得到一次 `pass` 和一次 `fail`。
- 生成 Git 忽略目录下的新规则与事实请求 JSON，并记录 SHA-256。

## 4. 范围外

- 修改、覆盖、删除或重新交接任何已持久化规则版本。
- 连接 MongoDB、执行 migration、调用 `persist` 或 `persist-handoffs`。
- 调用 DeepSeek、其他模型 Provider、SQL Server或任何网络服务。
- 修改 SqlBot、生成 SQL、发现数据库元数据、批准、发布或执行规则。
- 扩展当前四视图字段目录；无法精确确认的主视图字段继续 `unresolved`。

## 5. 验收标准

1. 旧 profile 仍能重建 2026-08-24 导出规则正文；旧规则与事实请求文件 SHA-256 保持不变。
2. 新 profile 使用同一 7,501 字符来源和完整 SHA-256 `562eabd40e5a5701fb9515499b542a6e2ff46056464621b1abb0a7c37f116e4d`。
3. 新候选包含 42 个事实：18 `source`、12 `aggregate`、4 `exists`、8 `derived`；34 个非派生事实均声明非空业务参数。
4. 新条件树包含 67 个唯一节点：14 `all`、9 `any`、1 `not`、43 `compare`；原始数据直接路径为显式双条件 `all`。
5. 14 个订单范围事实/派生事实使用 `grain=order`；流程存在性和特殊申请使用 `taskNumber`；运行时日期不再使用任务粒度或任务 ID。
6. `report.merge_flag` 不再错误限制为 `[0,1]`，值 `2` 的去重案例是合法案例输入。
7. 案例输入为 `null`、错误类型或不在非空 `allowedValues` 中时返回可定位的语义错误；默认校验不自动转换或补值。
8. 新 profile 至少包含 31 个案例，全部由解释器得到声明结果；每个条件节点在案例集合中至少出现一次 `pass` 和一次 `fail`。
9. 8 个旧映射候选中 6 个恢复为 `unresolved`，只保留 2 个字段级候选；所有映射继续为 `reviewStatus=candidate`，不得携带 `sourceExpression`。
10. 新结果固定为 `schemaVersion=2.0.0`、`status=draft`、`executable=false`，Parser 为 `reviewed_import / reviewed-import-v2 / codex-gpt-5`，规则版本与旧版本不同。
11. 新草稿确定性导出 34 条 `FactBindingRequest 2.0.0`，逐条通过 Pydantic、仓库内 Draft 2020-12 Schema 和安全文本门禁，且每条仍有 `blocking` 不确定性。
12. 离线导出脚本不加载 `Settings`、不创建 MongoDB/Provider 客户端、不提供持久化参数；输出只写用户指定的本地目录。
13. 相关单元测试、默认离线测试、Ruff、严格 Mypy 和 `pip check` 通过；测试不得访问网络、MongoDB、DeepSeek 或 SQL Server。

## 6. 安全和不可变边界

- 本次授权不包含任何数据库写入。即使新草稿全部门禁通过，也只能报告 `validated_not_persisted`。
- 新草稿是否持久化必须由用户在本任务完成后另行明确授权。
- 错误、命令输出和产物不得包含凭据、连接串、原始 Provider 响应或 SQL。
- `.obsidian/workspace.json` 的既有修改必须保留且不纳入本任务。

## 7. 完成结果

- 新未持久化草稿：`REPORT_RELEASE_ALL_001@20260827T013225952760Z-562eabd40e5a`。
- 规则导出 SHA-256：`5d67f0d26aea117ac16528095553c524a7f97bb74fdfb9a02b8cb519cd7dc108`。
- 事实请求导出 SHA-256：`2e97b9ab725cc5c9268f24d58559aea7638274994efdad2425f332db6070bb53`。
- 精确结构为 42 个事实、67 个条件、31 个案例和 2 个保留候选映射；67 个条件均获得 `pass/fail` 双向案例覆盖。
- 34 个非派生事实请求全部通过 Pydantic、静态 JSON Schema 和安全门禁，且 34 条全部保持 `blocking`。
- 本任务没有调用 DeepSeek、MongoDB、SQL Server 或网络；没有修改任何既有 `rule_versions` 或 `fact_binding_handoffs`。

本需求只关闭技术修订与离线产物生成，不表示新草稿已通过业务复审，也不授权持久化、发布或执行。
