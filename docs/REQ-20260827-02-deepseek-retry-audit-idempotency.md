# REQ-20260827-02：DeepSeek 重试、审计与幂等性治理

- 状态：`COMPLETED`
- 日期：2026-08-27
- 来源：用户选择任务 B，明确要求不与 Schema 2.0 草稿业务审核任务 A 同时展开
- 前置需求：[REQ-20260818-03](REQ-20260818-03-rule-parser.md)
- 业务决策：[BIZ-20260827-01](BIZ-20260827-01-deepseek-call-governance.md)
- 技术方案：[DEV-20260827-02](DEV-20260827-02-deepseek-retry-audit-idempotency.md)
- 历史问题证据：[PROG-20260819](PROG-20260819.md)
- 完成证据：[PROG-20260827](PROG-20260827.md)

## 1. 背景

Rule Parsing Agent 已对 Provider 超时、传输失败、限流、服务端错误、空响应及候选 JSON/Schema/语义错误执行有上限的重试，但当前重试立即发生，最终结果只保留一个整数尝试次数，DeepSeek 响应中的请求标识和 token usage 被丢弃。同一解析请求重复提交时也会重新调用 Provider，并生成新的时间戳规则版本。

这使费用核对、问题定位和客户端安全重放缺少确定性证据。本需求只治理 DeepSeek 解析调用链，不继续任务 A 的业务审核，不修改任何既有 Schema 2.0 草稿、MongoDB 规则版本或事实交接记录。

## 2. 目标

- 对所有可重试失败实施有上限的指数退避，且尝试总数继续受现有 `max_retries + 1` 约束。
- 为每次解析生成应用 request ID，逐次记录退避时长、结果代码、可重试性、Provider request ID 和可获得的 token usage。
- 在成功草稿和最终错误中返回同一套安全审计信息，支持费用核对和故障定位。
- 接受显式请求幂等键；同一进程内，相同键和相同解析身份只执行一次 Provider 工作并精确重放结果。
- 对相同幂等键绑定不同解析身份的请求 fail closed，不调用 Provider。
- 不记录或输出 DeepSeek Key、原始幂等键、完整 Prompt、完整来源文本或原始 Provider 响应。

## 3. 范围内

- 应用版本升级到 `0.10.0`；Python 保持 `3.11.9`，MongoDB Schema 保持 v3，规则 Schema 保持 `2.0.0`。
- 为 DeepSeek 重试增加集中配置的基础退避和最大退避秒数。
- Provider 适配器返回经过边界校验的候选文本、DeepSeek completion `id` 和可用 token usage；不得把 SDK 类型传入领域层或 LangGraph state。
- Parser 元数据新增可选调用审计；历史导入及既有持久化文档没有审计字段时保持原 JSON 形状。
- 最终失败的稳定错误契约新增可选调用审计。
- HTTP `Idempotency-Key` header 和 CLI `--idempotency-key` 作为可选客户端幂等键入口。
- 使用 SHA-256 摘要绑定幂等键和解析身份；只在进程内使用有界 LRU 成功缓存和并发请求合并。
- 相同键、相同解析身份的已完成成功请求返回完全相同的 `RuleParseResultV2`，包括 `ruleVersion`、`generatedAt` 和审计 request ID；不再次调用 DeepSeek。
- 相同键、不同解析身份返回 `IDEMPOTENCY_KEY_CONFLICT`；格式不合法返回 `IDEMPOTENCY_KEY_INVALID`。
- `persist=true` 重放继续依赖现有不可变 `rule_versions` 保存幂等性；本需求不改变数据库写入协议。

## 4. 范围外

- 继续或重做任务 A 的 41/42 个事实、65/67 个条件、案例和候选映射业务审核。
- 修改、覆盖、删除或重新交接任何已持久化 `rule_versions` 或 `fact_binding_handoffs`。
- 新增 MongoDB 集合、migration、分布式锁、共享缓存、审计表或跨进程幂等保证。
- 向 DeepSeek 发送未经其官方契约确认的幂等 header，或把 `user`/`user_id` 字段误作幂等键。
- 自动无限重试、后台补偿任务、队列、熔断器或新的 Agent 框架。
- 记录原始请求/响应、Prompt、业务正文、API Key 或其他凭据。
- 默认测试调用真实 DeepSeek、网络或 MongoDB。

## 5. 验收标准

1. 第一次 Provider 尝试不等待；第 2 次起按 `min(base_delay * 2^(attempt-2), max_delay)` 等待，非可重试错误和最后一次失败后不再等待。
2. `deepseek_max_retries=2` 时最多调用 Provider 3 次；超时、限流、可用性错误及候选 JSON/Schema/语义错误继续遵守既有 retryable 分类。
3. 成功结果审计准确给出 request ID、`attemptCount`、逐次 `backoffSeconds/outcomeCode/retryable`、Provider request ID、逐次及汇总 token usage。
4. 最终失败错误携带截至失败时的同一审计结构；输入门禁失败时 `attemptCount=0` 且不调用 Provider。
5. DeepSeek 成功响应缺少或非法 completion `id` 时按 `PROVIDER_RESPONSE_INVALID` 处理；token usage 缺失时不伪造数值，也不因此把有效候选改写为无效。
6. 相同幂等键与相同解析身份的顺序重放只调用一次 Provider，并返回相同规则版本；并发重放共享同一在途任务。
7. 相同幂等键绑定不同来源正文、来源标识、解析器/Prompt/模型或 Schema 身份时返回 HTTP 409 对应错误，且 Provider 调用数不增加。
8. 幂等缓存只保存成功结果、容量有上限；失败不长期缓存，允许客户端随后重新尝试。
9. 审计和日志不包含原始幂等键、完整来源文本、完整 Prompt、原始 Provider 响应、DeepSeek Key 或 MongoDB URI；只允许输出幂等键 SHA-256。
10. 没有幂等键时保持既有行为：每次请求是独立解析；旧调用方无需修改即可继续工作。
11. reviewed import、既有 V1/V2 夹具、历史规则及事实交接 canonical hash 不因可选审计字段改变。
12. 单元测试覆盖退避边界、尝试审计、Provider 元数据、幂等顺序/并发重放、冲突、失败后重试和缓存上限；默认测试使用替身 sleeper/Provider，不发生真实等待或网络调用。
13. 相关单元测试、默认离线测试、Ruff、严格 Mypy 和 `pip check` 通过。

## 6. 安全与运行边界

- 客户端幂等键长度和字符集必须在入口处校验；内部只使用其 SHA-256 摘要作为索引和审计值。
- Provider request ID 只接受有界字符串；token 数只接受非负整数。
- Provider 原始响应不得进入 LangGraph state、日志、错误 details 或持久化文档。
- 进程内幂等缓存会在进程重启后丢失，也不在多个 worker 间共享；API 和文档必须明确这一限制。
- `.obsidian/workspace.json` 的既有修改必须保留且不纳入本任务。

## 7. 完成条件

本需求只有在文档、实现、测试和进度记录一致，且能给出不访问真实 DeepSeek/MongoDB 的可重复验证证据后才能标记 `COMPLETED`。本任务不构成对任何规则草稿的业务批准、持久化、发布或执行授权。

## 8. 完成结果

- 应用已升级到 `0.10.0`；MongoDB Schema v3、规则 Schema `2.0.0`、既有规则和事实交接均未修改。
- DeepSeek adapter、LangGraph、HTTP 和 CLI 已实现本需求的 Provider 元数据、退避、审计和进程内幂等行为。
- 默认离线测试为 `83 passed, 3 deselected`；Ruff、严格 Mypy（43 个源码文件）和 `pip check` 通过。
- 验证未调用真实 DeepSeek、网络或 MongoDB；`.obsidian/workspace.json` 的既有修改保持未触碰。
