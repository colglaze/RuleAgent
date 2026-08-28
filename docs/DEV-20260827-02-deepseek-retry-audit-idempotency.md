# DEV-20260827-02：DeepSeek 重试、审计与幂等性实现方案

- 状态：`IMPLEMENTED`
- 日期：2026-08-27
- 来源 REQ：[REQ-20260827-02](REQ-20260827-02-deepseek-retry-audit-idempotency.md)
- 业务决策：[BIZ-20260827-01](BIZ-20260827-01-deepseek-call-governance.md)
- 前置 DEV：[DEV-20260818-02](DEV-20260818-02-rule-parser.md)
- 完成证据：[PROG-20260827](PROG-20260827.md)

## 1. 版本和契约

- 应用版本：`0.9.0 -> 0.10.0`。
- Python：`3.11.9`；MongoDB Schema：v3；规则 Schema：`2.0.0`，均不变。
- 新增 Provider-neutral `CandidateGeneration` 返回值，包含候选正文、Provider request ID 和可选 token usage。
- 新增领域审计模型 `ProviderTokenUsage`、`ParseAttemptAudit` 和 `ParseAudit`；模型不得引用 DeepSeek SDK 类型。
- `ParserMetadata.audit` 和 `ParseIssue.audit` 均为可选；`None` 序列化时必须排除。

建议的外部 JSON 形状：

```json
{
  "requestId": "6d2c1c4f-70f4-4c3b-9fbe-b8f73d87ea37",
  "idempotencyKeySha256": null,
  "maxAttempts": 3,
  "attemptCount": 1,
  "totalBackoffSeconds": 0.0,
  "attempts": [
    {
      "attempt": 1,
      "backoffSeconds": 0.0,
      "outcomeCode": "CANDIDATE_JSON_INVALID",
      "retryable": true,
      "providerRequestId": "...",
      "tokenUsage": {
        "promptTokens": 100,
        "completionTokens": 20,
        "totalTokens": 120
      }
    }
  ],
  "totalTokenUsage": {
    "promptTokens": 100,
    "completionTokens": 20,
    "totalTokens": 120
  }
}
```

## 2. 配置

`Settings` 新增：

```text
DEEPSEEK_RETRY_BASE_DELAY_SECONDS=1.0
DEEPSEEK_RETRY_MAX_DELAY_SECONDS=8.0
DEEPSEEK_IDEMPOTENCY_CACHE_MAX_ENTRIES=64
```

约束：基础/最大退避均非负，最大退避不得小于基础退避，缓存容量至少为 1 且有保守上限。公开配置摘要只暴露非敏感数值，不暴露 key、连接串或幂等内容。

## 3. Provider 边界

`DeepSeekRuleCandidateModel.generate_candidate` 在 SDK 边界完成以下处理：

1. 保持既有异常到稳定 `ParseErrorCode` 的映射；
2. 校验 `choices[0].message.content` 为非空字符串；
3. 校验 completion `id` 为 1 至 256 字符的字符串；缺失或越界返回 retryable `PROVIDER_RESPONSE_INVALID`；
4. 从 `usage` 读取非负整数；标准 prompt/completion/total 三项不能完整可信时整组 usage 置空；可选缓存和推理子项只在合法时保留；
5. 返回 `CandidateGeneration`，不返回 SDK response，也不记录原始 response。

## 4. LangGraph 状态和退避

`ParserState` 增加 request ID、幂等键摘要、当前退避和完整尝试审计列表。节点仍保持单一职责：

```text
prepare_input
  -> invoke_model（根据下一尝试序号先调用注入的 async sleeper）
  -> validate_candidate（更新当前尝试 outcome）
  -> build_result（写 parser.audit）
  -> error（把 audit 附到最终 ParseIssue）
```

第 `attempt` 次调用前的退避：

```text
attempt == 1: 0
attempt >= 2: min(base_delay * 2 ** (attempt - 2), max_delay)
```

只有路由已经确认存在下一次调用时才会进入该退避。测试注入异步 sleeper 记录秒数而不真实等待。

Provider 抛错时本次尝试直接以错误 code 结束。Provider 返回候选时先暂记为已收到响应，再由候选校验节点把同一条记录更新为 JSON、Schema、语义错误或 `SUCCESS`。token 汇总覆盖所有具有 usage 的尝试。

## 5. 幂等协调器

`RuleParsingService.parse_text` 和 `parse_to_json` 增加可选 `idempotency_key` 参数。实现使用：

- `asyncio.Lock` 保护有界 LRU 与在途表；
- `sha256(raw_key)` 作为唯一索引和对外摘要；
- 对 canonical JSON 解析身份再计算 SHA-256 fingerprint；
- `asyncio.Task[RuleParseResultV2]` 合并同键同 fingerprint 的并发调用；
- `OrderedDict` 保存成功结果，超出容量时淘汰最久未使用项。

解析身份 canonical JSON 包含原始 `text`、`sourceName`、`relativePath`、Schema `2.0.0`、应用 parser version、Prompt version、Provider 和 model。缓存不保存来源正文或原始键，只保存 fingerprint、结果对象和键摘要。

命中完成缓存时返回同一结果，不重新生成 request ID、时间戳或版本。fingerprint 冲突在创建 Provider task 前失败。Provider/校验失败时删除在途条目且不写完成缓存。

## 6. API 和 CLI

- HTTP 从 `Idempotency-Key` header 读取可选值并传给解析服务。
- 成功时从 `result.parser.audit.requestId` 设置 `X-RuleReader-Request-ID`。
- 失败时从 `error.audit.requestId` 设置相同 header；不得记录原始幂等键。
- `IDEMPOTENCY_KEY_INVALID -> 422`，`IDEMPOTENCY_KEY_CONFLICT -> 409`。
- OpenAPI 补充 409 错误响应。
- CLI 增加 `--idempotency-key`；JSON 成功/错误契约与应用服务一致。

## 7. 兼容性和持久化

- `ParserMetadata.audit` 使用字段级 `exclude_if` 排除 `None`，确保 reviewed import 和历史夹具不新增 `audit: null`。
- 新 Provider 生成草稿若执行既有 `persist=true`，审计随该不可变草稿保存；不创建独立审计记录。
- 同一幂等命中的结果具有同一 `ruleVersion`，重复 repository `save` 继续插入 0 条或命中既有不可变内容。
- 不修改 migration、`rule_versions` 唯一键、`fact_binding_handoffs` 或 canonical hash 算法。

## 8. 测试计划

- Provider 单元测试：completion ID/usage 正常提取，ID 缺失/过长，usage 缺失/非法，且不泄露原始 response。
- Workflow 单元测试：首次无等待，指数增长和封顶；Provider 失败与三类候选失败的逐次 outcome；成功/最终失败/输入失败审计；token 汇总。
- 幂等单元测试：无键独立执行；同键顺序命中；同键并发合并；异身份冲突；失败后可重试；LRU 淘汰；键格式门禁。
- API/CLI 单元测试：header/参数透传、request ID header、422/409 映射、错误 audit。
- 回归测试：reviewed import JSON 不出现 audit；历史规则、事实绑定导出和既有 canonical hash 不变。
- 配置测试：默认值、环境覆盖和 `max_delay >= base_delay` 门禁。

默认测试继续使用 `QueueModel`、假的 SDK client 和记录型 sleeper。不得运行真实 Provider integration；相关 integration 仍须显式环境开关。

## 9. 实施顺序

1. 先提交本 REQ/BIZ/DEV 决策到工作区；
2. 增加审计/Provider 返回契约及回归测试；
3. 实现适配器元数据提取；
4. 实现 LangGraph 退避和审计；
5. 实现进程内幂等协调与 HTTP/CLI 入口；
6. 运行近端测试、完整默认测试及静态门禁；
7. 更新 `docs/进度文档.md` 与当日 `PROG`，再把状态改为完成。

## 10. 实施结果

- `CandidateGeneration`、Provider-neutral 审计模型、DeepSeek completion ID/token usage 提取和稳定错误映射已实现。
- LangGraph 已按本方案记录每次尝试，并通过可注入 sleeper 执行确定性退避；失败候选产生的 token 也进入汇总。
- 有界进程内协调器已实现顺序重放、并发合并、fingerprint 冲突、失败后重试及 LRU 淘汰；缓存和审计均不保存原始幂等键。
- HTTP/CLI 入口、422/409 映射和 `X-RuleReader-Request-ID` 已实现；reviewed import 在无审计时仍排除 `audit` 字段。
- `83 passed, 3 deselected`，Ruff、严格 Mypy（43 个源码文件）和 `pip check` 全部通过；没有运行真实 Provider 或数据库 integration。
