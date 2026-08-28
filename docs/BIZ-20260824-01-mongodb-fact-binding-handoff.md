# BIZ-20260824-01：MongoDB 事实绑定交接所有权与不可变策略

- 状态：`ACCEPTED`
- 日期：2026-08-24
- 来源 REQ：[REQ-20260824-01](REQ-20260824-01-mongodb-fact-binding-handoff.md)
- 补充决策：[BIZ-20260819-01](BIZ-20260819-01-agent2-handoff-baseline.md)

## 1. 已确认决策

1. 集合名固定为 `fact_binding_handoffs`。
2. RuleReader 拥有该集合的数据契约、migration 和唯一写权限；SqlBot 是只读消费者，不能修改集合或记录。
3. 交接记录是某一不可变规则版本在当前 `FactBindingRequest 2.0.0` 契约下的确定性事实快照，不是事实注册中心、SQL 模板或规则发布记录。
4. 每个非 `derived` 事实恰好一条记录；`derived` 事实继续由规则 AST 确定性计算，不进入 SqlBot 事实绑定。
5. 唯一身份固定为 `<ruleVersion>#<factCode>`；同一身份只能拥有一个 canonical payload 哈希。
6. 相同身份和相同 payload 的重复交接是幂等重放；不同 payload 是不可变性冲突，RuleReader 必须拒绝且不得覆盖。
7. 交接只能从 RuleReader 自己的 `rule_versions` 精确回读；内存候选、HTTP 提交体、导出文件或 Schema `1.0.0` 历史规则均不能直接写入交接集合。
8. 全批次 payload 必须先通过 Pydantic、仓库内 JSON Schema 与安全门禁，再执行 MongoDB 写入。
9. blocking uncertainties 必须原样保留。交接集合允许保存 blocked 请求，但 SqlBot 必须在其自身 intake 中阻止后续 SQL 候选生成。
10. 本阶段只提供显式运维 CLI 创建交接，不新增公开写入 HTTP 接口，避免把交接写入隐式绑定到解析或读取请求。
11. RuleReader 不配置或保存 SqlBot、SQL Server 或其他系统的连接凭据。SqlBot 的 MongoDB 只读角色由部署环境独立配置。

## 2. 所有权边界

| 集合 | 所有者 | RuleReader | SqlBot |
| --- | --- | --- | --- |
| `rule_versions` | RuleReader | 不可变写入、精确回读 | 不直接修改 |
| `fact_binding_handoffs` | RuleReader | migration、不可变写入、校验与回读验证 | 只读消费 |
| SqlBot 自有集合 | SqlBot | 不读写，除非后续独立契约明确授权 | migration 与业务写入 |

共享 MongoDB 实例不改变集合所有权。任何跨服务引用只使用不可变 ID、版本、契约版本和内容哈希。

## 3. 不可变写入语义

```text
persisted RuleParseResultV2
→ deterministic FactBindingRequestV2[]
→ Pydantic + checked-in JSON Schema + safety validation
→ canonical JSON SHA-256
→ preflight existing IDs and hashes
→ insert missing immutable records
→ read-back exact rule handoff set and verify source rule unchanged
```

- 不使用 `replace` 或 `$set` 更新业务记录。
- 首次创建时间只在 insert 时写入；幂等重放不刷新时间。
- 冲突是确定性数据治理错误，不通过“最后写入获胜”解决。
- 一个规则版本的现有交接集合若多出、缺少或包含不同哈希，整次验证失败，不能对 SqlBot 报告完整交接成功。

## 4. 索引决策

- 保留 MongoDB `_id_` 唯一索引，`_id=requestId`。
- 建立 `uq_fact_binding_handoffs_request_id` 唯一索引，防止包装字段与 `_id` 的业务唯一性漂移。
- 建立 `uq_fact_binding_handoffs_rule_version_fact_code` 唯一联合索引；前缀满足按规则版本读取需求。

当前不建立全文、状态、时间或 payload 哈希索引。

## 5. 明确不授权

- RuleReader 推测或修复未决查询语义。
- RuleReader 生成、保存、审核或执行 SQL。
- 修改现有 `rule_versions`、把草稿改成可执行状态，或把交接成功解释为业务批准。
- SqlBot 写入 `fact_binding_handoffs`。
