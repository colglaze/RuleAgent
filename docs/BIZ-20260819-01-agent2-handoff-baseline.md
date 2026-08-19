# BIZ-20260819-01：双 Agent 事实交接基线

- 状态：`ACCEPTED`
- 日期：2026-08-19
- 来源 REQ：[REQ-20260819-01](REQ-20260819-01-rule-contract-v2-agent2-handoff.md)
- 替代范围：长期方案中未冻结的 Agent 2 交接细节

## 1. 已确认决策

1. RuleReader 与 `C:\Users\tao.chen\PycharmProjects\SqlBot` 保持两个独立 Python 服务；前者是 Agent 1，后者是 Agent 2。
2. Agent 2 不把整条规则转换为一条异常集合 SQL，而是为尚未建立正式 Provider 的单个事实生成候选 SQL 模板。
3. 跨服务 JSON 使用 camelCase 和显式版本；Python 内部可以使用 snake_case。
4. RuleReader 新规则契约使用 Schema `2.0.0`。Schema `1.0.0` 归档保持不可变、可回读，但不能直接进入 Agent 2。
5. `derived` 事实由结构化表达式确定性计算，不要求 Agent 2 为其生成 SQL；`source`、`aggregate`、`exists` 事实可以进入事实绑定流程。
6. SqlBot 使用 Python `3.11.9`、LangGraph 和 DeepSeek；保留其已确认的 `uv` 包管理方式。
7. 首个目标 SQL 方言为 SQL Server。会话级临时表默认禁用，直到权限、版本和事务行为另行确认。
8. 两个服务可以连接同一 MongoDB 实例，但各自拥有集合和 migration；禁止跨服务直接修改对方集合。
9. RuleReader 只导出事实绑定请求，不读取目标数据库元数据；SqlBot 负责在后续阶段组合元数据快照并生成候选模板。

## 2. 交接边界

```text
RuleReader Schema 2.0 draft
→ deterministic FactBindingRequest[]
→ SqlBot intake validation
→ metadata snapshot + SQL Server context
→ SqlTemplateCandidate
→ SQL AST / read-only / parameter / coverage validation
→ human review
```

任一步缺少必需上下文时必须返回 `blocked`，不能要求模型猜测表、字段、JOIN、权限或参数来源。

## 3. MongoDB 所有权

- RuleReader 当前只拥有 `schema_migrations`、`app_metadata` 和 `rule_versions`。
- SqlBot 后续拥有自己的元数据快照、生成运行和 SQL 模板集合；集合名和索引由 SqlBot 的 REQ/DEV/migration 冻结。
- 跨服务引用只保存不可变 ID、版本和内容哈希，不嵌入或覆盖另一服务的业务载荷。

## 4. 当前仍不授权

- RuleReader 实现 SQL、数据库元数据或事实注册中心。
- SqlBot 执行生产 SQL、自动批准模板或创建临时表。
- 旧 Schema `1.0.0` 的自动迁移或覆盖。
