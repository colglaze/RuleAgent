# DEV-20260824-01：MongoDB 不可变事实绑定交接实现

- 状态：`IMPLEMENTED`
- 日期：2026-08-24
- 来源 REQ：[REQ-20260824-01](REQ-20260824-01-mongodb-fact-binding-handoff.md)
- 关联 BIZ：[BIZ-20260824-01](BIZ-20260824-01-mongodb-fact-binding-handoff.md)
- 前置 DEV：[DEV-20260819-01](DEV-20260819-01-rule-contract-v2.md)

## 1. 模块与依赖方向

```text
application/fact_binding_handoffs/ports.py
  不可变记录、批次结果、仓储 Protocol 和稳定错误

application/fact_binding_handoffs/service.py
  精确回读规则、V2 门禁、双重契约校验、canonical hash、批次编排和回读复核

infrastructure/fact_binding_handoffs.py
  MongoDB insert-only 仓储、冲突检测、完整记录回读

infrastructure/migrations.py
  Schema v3 集合和索引

cli.py
  显式 persist-handoffs --rule-version 入口与脱敏摘要
```

领域 `RuleParseResultV2` 和 `FactBindingRequestV2` 不依赖 MongoDB。应用用例只依赖规则版本仓储与交接仓储端口；基础设施层负责 BSON 转换和 PyMongo 异常脱敏。

## 2. MongoDB Schema v3

- `LATEST_SCHEMA_VERSION = 3`。
- v3 创建 `fact_binding_handoffs`，不修改 `rule_versions` 文档或索引。
- 索引：
  - 内建 `_id_`：`_id=request_id`；
  - `uq_fact_binding_handoffs_request_id`：`request_id` 升序、唯一；
  - `uq_fact_binding_handoffs_rule_version_fact_code`：`rule_version` 升序、`fact_code` 升序、唯一。
- v3 完成后只更新 `app_metadata.database_schema` 的版本、服务版本和更新时间。
- migration 从空库、v1、v2 执行及重复执行均保持幂等；v1/v2 migration 的历史版本号不能引用 future latest。

## 3. 应用用例

```text
persist(rule_version: str) -> PersistedFactBindingHandoffs
```

执行顺序固定为：

1. 通过 `RuleVersionRepository.get(rule_version)` 精确回读；不存在返回 `RULE_VERSION_NOT_FOUND`。
2. 必须得到 `RuleParseResultV2`；Schema `1.0.0` 返回 `RULE_SCHEMA_UNSUPPORTED_FOR_HANDOFF`，不调用 exporter 或交接仓储。
3. 调用既有 `build_fact_binding_requests_v2`；不解析来源、不调用 Provider、不补全不确定性。
4. 每个请求先以 `model_dump(by_alias=True, mode="json")` 得到完整 camelCase payload，再用 `FactBindingRequestV2.model_validate` 重新解析。
5. 使用 `jsonschema==4.26.0` 的 `Draft202012Validator` 与 `FormatChecker` 校验仓库内 `contracts/fact-binding-request-2.0.0.schema.json`；静态 Schema 本身先执行 `check_schema`。
6. 对每个 payload 运行既有 `validate_safe_structured_payload`。
7. 校验 `requestId == ruleVersion#factCode`、版本/事实/来源身份一致，并计算 canonical SHA-256。
8. 全部 payload 准备成功后调用交接仓储批次保存；任何前置失败都不得产生部分记录。
9. 按规则版本回读完整交接集合，逐条复算哈希并与预期 payload 比较；多出、缺少或变化均失败。
10. 再次回读来源规则，比较完整 `StoredRuleVersion`，确认业务文档与 `stored_at` 未改变。

`jsonschema` 从 dev-only 提升为精确固定的运行时依赖，因为静态 Schema 校验现在是生产写入门禁，而非仅测试工具。

## 4. Canonical payload 与记录模型

Canonical JSON 使用：

```python
json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
)
```

SHA-256 输入为上述字符串的 UTF-8 bytes。包装记录字段由已验证 payload 确定：

```text
_id = requestId
request_id = requestId
rule_version = payload.ruleRef.ruleVersion
fact_code = payload.fact.factCode
contract_version = payload.contractVersion
payload_sha256 = canonical payload SHA-256
created_at = one UTC BSON datetime generated for first insert
payload = complete camelCase payload
```

`created_at` 不进入 payload 或哈希。BSON 毫秒精度在返回前统一处理，确保首次写入与回读一致。

## 5. MongoDB 仓储算法

```text
save_many(prepared_records)
  reject duplicate IDs inside input
  find all existing _id values
  parse and verify every existing wrapper + Pydantic payload + canonical hash
  if any existing payload hash differs: raise FACT_BINDING_HANDOFF_HASH_CONFLICT
  insert_one each missing record
  on DuplicateKeyError: re-read and accept only exact same record
  return records in deterministic request order with inserted flags
```

- 预检保证已存在的冲突在新增写入前失败。
- 并发实例竞争同一 ID 时只允许一个 insert 成功；失败实例回读并验证完整相等。
- 仓储不提供 update/replace/delete。
- PyMongo 可用性问题转换为 `FACT_BINDING_HANDOFF_PERSISTENCE_UNAVAILABLE`；哈希/身份冲突使用不可重试的 `FACT_BINDING_HANDOFF_HASH_CONFLICT`。

## 6. CLI

```text
rule-reader persist-handoffs --rule-version <exact-rule-version>
```

- CLI 只创建 `MongoManager`、两个 MongoDB 仓储和交接应用服务，不创建 `DeepSeekChatModel` 或 `RuleParsingService`。
- 启动时先执行 Schema v3 migration。
- stdout 只返回脱敏 JSON 摘要：集合、规则版本、契约版本、总数、插入数、幂等既有数、blocking 请求数和来源规则未变化标记。
- stderr 错误只返回稳定 code/message/retryable，不输出 URI、原始 BSON 或完整 payload。

## 7. 测试

### 离线单元测试

- reviewed profile 从已持久化仓储替身产生 33 条准备记录；每条 request ID、包装身份、canonical hash 和 blocking uncertainties 正确。
- Pydantic 或静态 JSON Schema 失败时不调用交接仓储。
- 缺失版本和 Schema `1.0.0` 明确拒绝。
- 相同哈希重放返回幂等；不同 payload 哈希返回稳定冲突且不覆盖。
- 交接完成后来源规则仓储记录发生变化时验证失败。

### MongoDB integration

- 随机测试库从 Schema v2 升级到 v3并重复执行，验证集合、migration 和索引。
- 保存 reviewed profile 规则，再交接恰好 33 条；逐条校验 wrapper、Pydantic、静态 JSON Schema、canonical hash 和 blocking uncertainties。
- 再次执行插入数为 0，记录和 `created_at` 不变。
- 构造同一 request ID 的不同合法 payload，验证哈希冲突且原记录不变。
- 保存 Schema `1.0.0` 历史规则并验证拒绝、零交接；交接前后两个 `rule_versions` 原始 BSON 与数量完全一致。

默认测试继续排除 `integration` 与真实 Provider，任何测试都不访问 SQL Server。

## 8. 正式验收步骤

1. 只读记录正式库 `rule_versions` 总数、目标 V2 与历史 V1 的精确 BSON 哈希/`stored_at` 摘要。
2. 执行 Schema v3 migration 和一次 `persist-handoffs`。
3. 再执行一次相同命令验证 0 插入幂等重放。
4. 只读核对 `fact_binding_handoffs` 对目标规则恰好 33 条、所有哈希与 payload 有效、所有现有 blocking uncertainties 保留。
5. 复核 `rule_versions` 总数、目标 V2 与历史 V1 摘要均与步骤 1 一致。

全过程不得调用 DeepSeek、读取源 Markdown、访问 SQL Server 或输出凭据。
