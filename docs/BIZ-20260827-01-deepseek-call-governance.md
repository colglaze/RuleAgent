# BIZ-20260827-01：DeepSeek 调用治理决策

- 状态：`CONFIRMED`
- 日期：2026-08-27
- 来源 REQ：[REQ-20260827-02](REQ-20260827-02-deepseek-retry-audit-idempotency.md)
- 技术方案：[DEV-20260827-02](DEV-20260827-02-deepseek-retry-audit-idempotency.md)
- 被补充决策：[BIZ-20260818-03](BIZ-20260818-03-python311-deepseek.md)

## 1. 决策摘要

RuleReader 继续只使用 DeepSeek 作为规则解析模型 Provider，并在应用层治理有限重试、调用审计和安全重放。重试不能隐式放大为无限调用；Provider 返回的标识和计量数据只作为审计证据，不能改变规则业务语义。

DeepSeek 当前公开契约提供 completion `id` 和 `usage`，但没有本项目可依赖的 Provider 端幂等请求契约。因此 RuleReader 不发送自定义或猜测的 Provider 幂等 header，而是在自身解析用例边界提供可选、进程内幂等能力。

## 2. 重试决策

- `deepseek_max_retries` 表示首次调用之后允许的重试数；总尝试数恒为 `max_retries + 1`。
- 首次调用无退避；每次确定要重试后，下一次尝试前执行有上限的指数退避。
- 使用确定性退避，不加入随机 jitter，便于离线测试和逐次审计；未来若需多实例抗惊群，必须另立 REQ/BIZ。
- 只有现有稳定错误分类中 `retryable=true` 的错误可进入下一次尝试。
- 非可重试错误、输入门禁错误和最后一次失败立即结束，不再 sleep。
- 候选 JSON、Schema 或确定性语义校验失败仍可把可定位反馈传给下一次模型调用，但不得把失败候选持久化。

## 3. 审计决策

每次解析具有一个 RuleReader request ID。审计按 Provider 尝试记录：

- 尝试序号和该次调用前的退避秒数；
- 稳定 outcome code 和 retryable；
- DeepSeek completion `id`；
- 可获得的 prompt、completion、total token 数及 DeepSeek 明确返回的缓存/推理 token 子项。

成功响应后的 JSON/Schema/语义失败归属于产生该候选的同一次 Provider 尝试。最终有效候选把该次 outcome 标记为 `SUCCESS`。汇总 token usage 对所有已返回 usage 的尝试求和，包括后来因候选无效而重试的调用，因为这些调用已经产生费用。

审计不得包含来源正文、Prompt、候选原文、Provider 原始响应、异常堆栈或任何凭据。Provider request ID 缺失视为响应契约无效；usage 缺失则明确保持为空，不推算或伪造。

## 4. 幂等决策

- 客户端可通过 HTTP `Idempotency-Key` 或 CLI `--idempotency-key` 提供 8 至 128 字符的受控键。
- 原始键只用于入口校验和立即计算 SHA-256；缓存索引、日志和响应只使用摘要。
- 幂等身份绑定来源原文、`sourceName`、`relativePath`、规则 Schema、Parser/Prompt 版本和 Provider/model。上述任一内容变化，复用同一键必须冲突。
- 幂等只包围“生成并验证规则草稿”的解析用例。`persist` 是对已生成结果的后续动作，不参与 Provider 解析身份；同一成功结果重复保存继续由不可变版本仓储保证幂等。
- 同一进程内，同键同身份的并发请求合并为一个在途任务；成功结果进入有界 LRU，后续请求精确重放。
- 失败结果不进入完成缓存。并发等待者可以观察同一次失败；该在途任务结束后，新请求可以重新尝试。
- 没有幂等键时不做推断或内容级自动去重，每个请求保持独立。

## 5. 兼容性决策

- 应用版本升级为 `0.10.0`；规则 Schema `2.0.0` 和 MongoDB Schema v3 不变。
- 新 Provider 解析结果在 `parser.audit` 中携带可选审计；reviewed import 和历史文档不生成该字段。
- 可选字段为 `None` 时必须从 JSON 序列化中排除，避免改变旧文档和 canonical hash。
- API 成功与错误均返回 `X-RuleReader-Request-ID`（当 request ID 已建立时）；错误主体继续使用稳定 `error` envelope。
- 幂等键格式错误为 422；同键异身份冲突为 409；现有 Provider 错误 HTTP 分类保持不变。

## 6. 非决策与后续范围

以下能力本次不承诺：跨重启或跨 worker 幂等、共享缓存、审计检索、费用账单对账、Provider 级幂等、自动补偿、分布式限流及任务队列。若生产部署需要这些能力，必须先明确数据保留、安全权限和 MongoDB/外部基础设施方案，再建立新的 REQ/BIZ/DEV。

## 7. Provider 契约依据

- [DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)：响应 completion `id` 和 `usage` 字段。
- [DeepSeek Token Usage](https://api-docs.deepseek.com/quick_start/token_usage/)：token 计量口径。
- [DeepSeek Rate Limit](https://api-docs.deepseek.com/quick_start/rate_limit)：限流行为说明。

截至本决策日期，上述官方页面没有提供本项目可依赖的请求幂等 header 契约，因此本实现不得自行推断或转发客户端幂等键。
