# BIZ-20260819-01：双 Agent 事实交接基线

- 状态：`ACCEPTED`
- 日期：2026-08-19
- 更新日期：2026-08-24
- 来源 REQ：[REQ-20260819-01](REQ-20260819-01-rule-contract-v2-agent2-handoff.md)
- 替代范围：长期方案中未冻结的 Agent 2 交接细节
- 后续 MongoDB 交接决策：[BIZ-20260824-01](BIZ-20260824-01-mongodb-fact-binding-handoff.md)

## 1. 已确认决策

1. RuleReader 与独立 `SqlBot` 仓库保持两个 Python 服务；前者是 Agent 1，后者是 Agent 2。
2. Agent 2 不把整条规则转换为一条异常集合 SQL，而是为尚未建立正式 Provider 的单个事实生成候选 SQL 模板。
3. 跨服务 JSON 使用 camelCase 和显式版本；Python 内部可以使用 snake_case。
4. RuleReader 新规则契约使用 Schema `2.0.0`。Schema `1.0.0` 归档保持不可变、可回读，但不能直接进入 Agent 2。
5. `derived` 事实由结构化表达式确定性计算，不要求 Agent 2 为其生成 SQL；`source`、`aggregate`、`exists` 事实可以进入事实绑定流程。
6. SqlBot 使用 Python `3.11.9`、LangGraph 和 DeepSeek；保留其已确认的 `uv` 包管理方式。
7. 首个目标 SQL 方言为 SQL Server。会话级临时表默认禁用，直到权限、版本和事务行为另行确认。
8. 两个服务可以连接同一 MongoDB 实例，但各自拥有集合和 migration；禁止跨服务直接修改对方集合。
9. RuleReader 只导出事实绑定请求，不读取目标数据库元数据；SqlBot 负责在后续阶段组合元数据快照并生成候选模板。
10. `FactBindingRequest 2.0.0` 是补齐查询语义后的新主版本；增加必填查询结构属于破坏性变化，不得原地扩展 `1.0.0`。
11. 2026-08-24 用户明确结束旧版过渡：`1.0.0` 只作为历史兼容夹具冻结保留，RuleReader 运行时无参数和显式请求均只输出 `2.0.0`；SqlBot intake 未升级是其独立阻塞，不构成 RuleReader 降级授权。本项替代同日较早记录的“默认返回 `1.0.0`”决定。
12. Agent 1 只能声明从规则草稿确定得到的逻辑实体、字段角色、筛选、聚合和时间范围。缺少事实级语义时必须通过 `unresolved + blocking uncertainty` 交接，不能把描述文本、候选视图字段或目录表达式提升为已确认 SQL 设计。
13. 2026-08-24，在两批各最多 3 次的真实 DeepSeek 重解析均被可信校验拒绝后，用户明确授权对同一来源执行一次受控 `reviewed_import`。该路径是离线治理动作，不接入新的运行时模型 Provider，不再次调用 DeepSeek，也不得冒充 DeepSeek 输出；必须记录独立 Provider、作者模型标识、导入契约版本和同一来源 SHA-256。
14. `reviewed_import` 仅能导入显式评审的 Schema `2.0.0` 候选，并继续经过 Pydantic、确定性语义解释器、规则专项审计、事实请求 Pydantic/JSON Schema 双重验证。任一门禁失败均禁止写入；成功后仍只是 `draft`、`executable=false`，不等同于业务批准。

## 2. 交接边界

```text
RuleReader Schema 2.0 draft
→ deterministic FactBindingRequest 2.0.0[]
→ SqlBot intake validation
→ metadata snapshot + SQL Server context
→ SqlTemplateCandidate
→ SQL AST / read-only / parameter / coverage validation
→ human review
```

任一步缺少必需上下文时必须返回 `blocked`，不能要求模型猜测表、字段、JOIN、权限或参数来源。

受控 `reviewed_import` 不改变上述交接边界。它只替换失败的候选生成步骤，不能跳过验证、扩展 RuleReader 的 SQL/元数据职责，或把 `blocking` 不确定性解释为可生成 SQL。

`FactBindingRequest 2.0.0` 的 `declared` 表示来源于已校验规则草稿，`candidate` 表示未审核来源提示，`unresolved` 表示缺少决定性信息。草稿可携带阻断项持久化；只有 `blocking` 不确定性被显式解决、元数据快照就绪且 SqlBot 自身门禁通过后，才可进入候选生成。

## 3. MongoDB 所有权

- RuleReader 当前拥有 `schema_migrations`、`app_metadata`、`rule_versions` 和 [BIZ-20260824-01](BIZ-20260824-01-mongodb-fact-binding-handoff.md) 定义的 `fact_binding_handoffs`；后者仍由 RuleReader 唯一写入，SqlBot 只读。
- SqlBot 后续拥有自己的元数据快照、生成运行和 SQL 模板集合；集合名和索引由 SqlBot 的 REQ/DEV/migration 冻结。
- 跨服务引用只保存不可变 ID、版本和内容哈希，不嵌入或覆盖另一服务的业务载荷。

## 4. 当前仍不授权

- RuleReader 实现 SQL、数据库元数据或事实注册中心。
- SqlBot 执行生产 SQL、自动批准模板或创建临时表。
- 旧 Schema `1.0.0` 的自动迁移或覆盖。
