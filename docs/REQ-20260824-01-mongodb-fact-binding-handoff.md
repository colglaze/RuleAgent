# REQ-20260824-01：MongoDB 不可变事实绑定交接

- 状态：`COMPLETED`
- 日期：2026-08-24
- 来源：用户明确要求将已持久化 Schema `2.0.0` 规则确定性交接给 SqlBot
- 前置需求：[REQ-20260819-01](REQ-20260819-01-rule-contract-v2-agent2-handoff.md)
- 业务决策：[BIZ-20260824-01](BIZ-20260824-01-mongodb-fact-binding-handoff.md)
- 技术方案：[DEV-20260824-01](DEV-20260824-01-mongodb-fact-binding-handoff.md)

## 1. 背景

RuleReader 已能从不可变 Schema `2.0.0` 草稿确定性导出 `FactBindingRequest 2.0.0`，但现有 HTTP 导出是即时只读结果，没有形成可供独立 SqlBot 稳定读取的 MongoDB 交接记录。本需求只增加 RuleReader 所有的不可变交接集合，不改变规则草稿、不实现 SqlBot、SQL 或目标数据库访问。

首个交接来源固定为已持久化规则：

```text
REPORT_RELEASE_ALL_001@20260824T080726492666Z-562eabd40e5a
```

该规则的 `schemaVersion` 必须为 `2.0.0`，并应确定性产生 33 条非派生事实请求。本任务不得重新调用 DeepSeek、重新解析来源或覆盖、替换、删除任何 `rule_versions` 记录。

## 2. 目标

- 新增 RuleReader 独占写入、SqlBot 只读的 `fact_binding_handoffs` 集合。
- 为每个非 `derived` 事实保存一条完整 camelCase `FactBindingRequest 2.0.0`。
- 使用 `<ruleVersion>#<factCode>` 作为确定性 `requestId`、MongoDB `_id` 和业务请求标识。
- 对 canonical payload 计算 SHA-256；同一请求和同一哈希重复交接幂等成功，不更新时间或载荷。
- 同一 `requestId` 出现不同 payload 哈希时 fail-fast，禁止覆盖。
- 只有从 `rule_versions` 精确回读并通过 `RuleParseResultV2` 校验的规则才能产生记录。

## 3. 范围内

- MongoDB Schema v3 migration、集合和必要索引。
- 独立事实交接应用用例、不可变仓储端口及 MongoDB 适配器。
- 显式 CLI：`rule-reader persist-handoffs --rule-version <ruleVersion>`。
- 写入前逐条执行 `FactBindingRequestV2` Pydantic 校验、受控安全文本校验，以及仓库内 [Draft 2020-12 Schema](../contracts/fact-binding-request-2.0.0.schema.json) 校验。
- 写入后按 `ruleVersion` 回读并核对记录集合、哈希和完整 payload，同时复核来源 `rule_versions` 记录未变化。
- 离线单元测试和显式 MongoDB integration 测试。

## 4. 范围外

- 调用 DeepSeek、重新解析 Markdown、修正或补齐 blocking uncertainties。
- 修改、覆盖、迁移、批准、发布或删除任何历史规则草稿。
- 在 RuleReader 内实现 SqlBot、SQL 生成/校验/执行、目标 SQL Server 访问或元数据发现。
- 保存 SQL Server 连接串、数据库账号、密码、访问令牌或其他凭据。
- 为 SqlBot 创建数据库用户或变更部署环境权限；部署方必须单独授予 SqlBot 对交接集合的只读权限。
- 面向交接记录的更新、删除、补丁或覆盖接口。

## 5. 记录契约

```text
fact_binding_handoffs
  _id: requestId
  request_id: requestId
  rule_version: exact immutable ruleVersion
  fact_code: non-derived factCode
  contract_version: "2.0.0"
  payload_sha256: SHA-256(canonical payload UTF-8 bytes)
  created_at: UTC BSON datetime
  payload: complete camelCase FactBindingRequest 2.0.0
```

Canonical payload 固定为完整 camelCase payload 的 UTF-8 JSON：对象键按字典序排序、无非语义空白、保留 Unicode、禁止 NaN/Infinity。`payload_sha256` 不包含 MongoDB 包装字段或 `created_at`。

## 6. 所有权、不可变性与幂等性

- RuleReader 是 `fact_binding_handoffs` 的唯一写入方和 migration 所有者。
- SqlBot 只能读取交接记录；不得更新、覆盖、删除或为该集合建 migration。
- 仓储只暴露 insert/idempotent-save 和按规则版本回读，不提供 update、replace、delete 或 upsert 覆盖。
- 重复请求只有在 `_id/request_id/rule_version/fact_code/contract_version/payload_sha256/payload` 全部一致时才是幂等成功，并保留首次 `created_at`。
- 同一 `requestId` 的 canonical payload 哈希不一致，或已有记录内部身份/哈希不一致，必须返回稳定冲突错误且不覆盖已有记录。
- 一个批次必须先完成全部 33 条 payload 校验和既有记录冲突预检，再插入缺失记录。

## 7. 索引

- MongoDB 内建 `_id_` 唯一索引：保证确定性 `requestId` 唯一。
- `uq_fact_binding_handoffs_request_id`：`request_id` 唯一，显式保护业务标识。
- `uq_fact_binding_handoffs_rule_version_fact_code`：`rule_version + fact_code` 唯一，同时支持 SqlBot 按 `rule_version` 顺序读取。

不为尚未存在的搜索或管理需求增加额外索引。

## 8. 验收标准

1. MongoDB 可从 Schema v2 幂等升级到 v3；重复 migration 不改变既有规则或交接记录。
2. 新集合和三项唯一性约束（内建 `_id_`、业务请求 ID、规则版本与事实编码）存在。
3. 指定 Schema `2.0.0` 规则从 `rule_versions` 精确回读后生成并保存恰好 33 条记录；8 个 `derived` 事实不保存。
4. 每条 `_id == request_id == payload.requestId == <ruleVersion>#<factCode>`，包装字段与 payload 身份一致。
5. 每条 payload 均通过 `FactBindingRequestV2.model_validate`、仓库内静态 JSON Schema 和安全文本门禁。
6. 每条 `payload_sha256` 等于 canonical payload SHA-256；33 条 payload 原样保留所有 uncertainties，所有既有 `blocking` 项不被删除、改写或补齐。
7. 第二次交接同一规则返回 33 条既有记录、插入数为 0，payload、哈希和首次 `created_at` 均不变。
8. 同一 `requestId` 但不同 canonical payload 的写入返回稳定哈希冲突错误，已有记录保持不变。
9. Schema `1.0.0` 历史规则被明确拒绝，且不产生任何交接记录。
10. integration 测试和正式验收均证明 `rule_versions` 记录数量、来源记录 BSON 内容和入库时间在交接前后不变。
11. 默认测试不访问 MongoDB、网络或 DeepSeek；MongoDB integration 必须显式启用并使用随机隔离库。
12. Ruff、严格 Mypy、默认测试、MongoDB integration 和 `pip check` 通过；进度文档记录集合、索引、记录数、命令与结果。

## 9. 安全边界

- 写入路径只读取配置中的 RuleReader MongoDB，不读取源 Markdown，也不构造模型客户端。
- 错误和 CLI 输出不得包含 MongoDB URI、DeepSeek Key、业务正文或完整 payload。
- blocking uncertainties 是交接载荷的一部分；RuleReader 不能为了让请求进入 SqlBot 而推测字段、筛选、聚合、时间范围或实体键。
- 交接成功只表示不可变载荷可供消费，不表示规则已审核、SQL 可生成或业务规则可执行。
