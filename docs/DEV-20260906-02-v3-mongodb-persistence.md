# DEV-20260906-02：V3 交付 MongoDB Schema v5 持久化实现方案

- 状态：`IMPLEMENTED_OFFLINE_AWAITING_REAL_WRITE_AUTHORIZATION`
- 日期：2026-09-06
- 来源需求：[REQ-20260906-01](REQ-20260906-01-v3-mongodb-persistence.md)
- 业务决策：[BIZ-20260906-02](BIZ-20260906-02-v3-mongodb-persistence.md)
- 前置设计：[DEV-20260905-02](DEV-20260905-02-v3-agent2-handoff-readiness.md)、
  [DEV-20260906-01](DEV-20260906-01-rule-parse-result-v3.md)

## 1. MongoDB Schema v5 migration

`src/rule_reader/infrastructure/migrations.py` 保持既有模式：

- `LATEST_SCHEMA_VERSION = 5`；
- `_apply_v5` 新建且仅新建 `rule_versions_v3` 与 `fact_binding_handoff_batches_v3`；
- `rule_versions_v3` 唯一索引：
  - `uq_rule_versions_v3_rule_version`：`rule_version` 唯一；
  - `uq_rule_versions_v3_source_catalog`：`rule_set_id + source_sha256 + catalog_digest` 唯一；
- `fact_binding_handoff_batches_v3` 唯一索引：
  - `uq_fact_binding_handoff_batches_v3_rule_version`：`rule_version` 唯一；
- migration 幂等（集合存在即跳过、索引按名幂等、`schema_migrations` 记录唯一且并发冲突时容忍
  `DuplicateKeyError`）、支持并发初始化、只更新 `app_metadata` 的
  `schema_version/service_version`；
- 不修改、不迁移 `rule_versions`、`fact_binding_handoffs`、`rule_structure_candidates_v3` 中的
  历史记录，不创建其他集合。

应用版本同步升级到 `0.12.0`：`pyproject.toml`、`src/rule_reader/core/version.py`、`README.md`
与直接绑定 `__version__` 的测试期望。历史不可变产物中的 parserVersion 不批量替换。

## 2. confirmed profile 版本解耦

`scripts/report_release_v3_confirmed_profile.py` 新增含义明确的常量
`CONFIRMED_PROFILE_PARSER_VERSION = "0.11.0"`，`_build_result` 的 `source.parserVersion` 与
`parser.parserVersion` 固定使用该常量，不再读取 `rule_reader.core.version.__version__`。详见
[BUG-20260906-02](BUG-20260906-02-confirmed-profile-version-coupling.md)。

## 3. 应用层（`src/rule_reader/application/v3_persistence/`）

领域模型不依赖 PyMongo、文件系统或 Settings；应用层只依赖领域类型。

### 3.1 canonical 序列化与哈希（`canonical.py`）

- `result_payload_v3(result)` / `request_payload_v3(request)`：`model_dump(mode="json",
  by_alias=True)` 的完整 camelCase JSON；
- `canonical_payload_json(payload)`：`json.dumps(payload, ensure_ascii=False, sort_keys=True,
  separators=(",", ":"), allow_nan=False)`，按 UTF-8 编码；
- `canonical_payload_sha256(payload)`：canonical JSON 的 SHA-256；
- `batch_sha256_v3(identities)`：输入为 `(requestId, payloadSha256)` 序列；先按 `requestId`
  升序排序，再对 `[{"requestId": ..., "payloadSha256": ...}, ...]` 取 canonical SHA-256。
  时间字段不进入任何 hash，因此同一交付跨重试 hash 稳定。

### 3.2 端口与记录（`ports.py`）

- 错误（均携带稳定脱敏 `code`，不携带 URI、凭据、payload 或原始 PyMongo 消息）：
  - `V3PersistenceError`：`V3_PERSISTENCE_FAILED`；
  - `V3PersistenceContractError`：`V3_PERSISTENCE_CONTRACT_INVALID`（写前门禁失败）；
  - `V3PersistenceConflictError`：`V3_PERSISTENCE_HASH_CONFLICT`（同 identity 异 hash）；
  - `V3PersistenceVerificationError`：`V3_PERSISTENCE_VERIFICATION_FAILED`（回读校验失败或
    存量文档损坏）；
  - `V3PersistenceUnavailableError`：`V3_PERSISTENCE_UNAVAILABLE`（PyMongo 失败，retryable）。
- `PreparedV3RuleVersion`：`rule_version`、`rule_set_id`、`schema_version="3.0.0"`、
  `source_sha256`、`catalog_digest`、`candidate_payload_sha256`、`payload_sha256`、
  `status="draft"`、`executable=False`、`payload`（完整 camelCase dict）。
- `PreparedV3RequestWrapper`：`request_id`、`rule_version`、`fact_code`、
  `contract_version="3.0.0"`、`payload_sha256`、`payload`。
- `PreparedV3HandoffBatch`：`rule_version`、`contract_version="3.0.0"`、`request_count`、
  `request_ids`（按 `requestId` 升序）、`batch_sha256`、`wrappers`（按 `requestId` 升序）。
- `StoredV3RuleVersion` / `StoredV3HandoffBatch`：prepared 记录 + `stored_at` / `created_at`；
  `SavedV3RuleVersion` / `SavedV3HandoffBatch`：stored 记录 + `inserted`。
- 仓储协议：`V3RuleVersionRepository.save/get`、`V3HandoffBatchRepository.save/get`、
  `V3LegacyCollectionCounter.count`。

### 3.3 服务（`service.py`）

`V3PersistenceService(rules, batches, counter, *, clock=None)` 接收
`BusinessConfirmedFactCatalogV3`、`RuleStructureCandidateV3`、`RuleParseResultV3` 与全部
`FactBindingRequestV3`，流程为：写前全量校验 → 快照三个历史集合计数 → 保存规则 → 保存 batch →
精确回读并重新校验 → 复核历史集合计数不变 → 返回脱敏摘要。

写前门禁（任一失败即 `V3PersistenceContractError`，零写入）：

1. candidate 无 blocking issue；
2. `result.status == "draft"` 且 `result.executable is False`；
3. `result.agent2_readiness_ready is True`；
4. `build_agent2_readiness_report_v3(candidate, catalog, result=result, requests=requests)`
   共 16 条门禁且全部 pass、`ready=true`；
5. result 闭包：`rule_set_id == candidate.rule_set_id`；`catalogRef` 与 catalog 的
   id/version/digest 一致；`candidateRef.payloadSha256 == candidate_payload_sha256_v3(candidate)`；
   `candidateRef.ruleBlockSha256 == source.sourceSha256`；
6. `validate_rule_structure_candidate_v3(candidate, catalog)` 通过，且重新导出
   `export_fact_binding_requests_v3` 的结果与输入 requests 按 `requestId` 集合逐一相等；
7. request 数量等于非派生 fact declaration 数量；每个非派生 fact 正好一条 request；
8. 每个 request：`request_id == f"{result.rule_version}#{fact_code}"`、
   `rule_ref.rule_version == result.rule_version`、`contract_version == "3.0.0"`；
9. request ID 与 fact code 无重复；
10. 逐 request 计算 canonical payload hash 与 batch hash。

幂等与冲突语义（insert-only，禁止 update/replace/delete/覆盖）：

- 相同 identity（`_id = ruleVersion`）+ 相同 canonical hash：幂等返回首次记录，保留首次
  `stored_at`/`created_at`；
- 相同 identity + 不同 hash：`V3PersistenceConflictError`，不覆盖；
- 规则已写入而 batch 暂时失败：重试依靠规则写入幂等安全恢复；不引入事务、消息队列或额外集合。

回读门禁（任一失败即 `V3PersistenceVerificationError`）：

- 规则 payload 可重新 `RuleParseResultV3.model_validate`；每个 request payload 可重新
  `FactBindingRequestV3.model_validate`；
- wrapper identity 与 payload 字段一致；payload hash 与重算 canonical hash 一致；
- batch 的 `request_count`、`request_ids`、wrapper 集合、排序与重算 batch hash 一致；
- `rule_versions`、`fact_binding_handoffs`、`rule_structure_candidates_v3` 的文档数量前后不变。

## 4. MongoDB 适配器（`src/rule_reader/infrastructure/v3_persistence.py`）

`MongoV3PersistenceRepository` 同时实现两个仓储协议与历史集合计数端口，沿用
`MongoFactBindingHandoffRepository` / `MongoV3RecoveryRepository` 模式：

- 文档结构：

```text
rule_versions_v3:
{
  "_id": ruleVersion, "rule_version", "rule_set_id", "schema_version": "3.0.0",
  "source_sha256", "catalog_digest", "candidate_payload_sha256", "payload_sha256",
  "status": "draft", "executable": false, "stored_at", "payload": <完整 camelCase JSON>
}
fact_binding_handoff_batches_v3:
{
  "_id": ruleVersion, "rule_version", "contract_version": "3.0.0",
  "request_count", "request_ids": [升序], "batch_sha256", "created_at",
  "requests": [
    { "request_id", "rule_version", "fact_code", "contract_version": "3.0.0",
      "payload_sha256", "created_at", "payload": <完整 camelCase JSON> }, ...
  ]
}
```

- 写入使用 `insert_one`；`DuplicateKeyError` 后回读既有文档：内容与 canonical hash 完全一致则
  幂等返回原记录（保留首次时间），否则 `V3PersistenceConflictError`；
- 其他 `PyMongoError` 统一转换为 `V3PersistenceUnavailableError`；
- 回读解析对 wrapper 类型、`_id` 一致性、契约版本、状态、executable、payload 重解析、
  wrapper-payload 闭包和 hash 全部复核，失败抛 `V3PersistenceVerificationError`；
- 时间统一为 UTC 毫秒精度 aware datetime（与既有适配器一致）。

## 5. 显式脚本（`scripts/persist_report_release_v3_delivery.py`)

- 参数 `--artifact-dir`；只读取该目录内的 confirmed 产物：
  `business-confirmed-fact-catalog-3.0.0.json`、`rule-structure-candidate-3.0.0.json`、
  `rule-parse-result-3.0.0.json`、`fact-binding-requests-3.0.0.json`、
  `v3-agent2-readiness-confirmed.json`、`confirmed-recovery-manifest.json`；
- 产物级校验（在任何数据库访问前完成）：全部文件可读、可 Pydantic 解析；manifest 记录的六个
  文件 SHA-256 与实际一致；manifest 的 `ruleVersion/requestCount/testCaseCount/
  agent2ReadinessReady` 与产物一致；readiness 文件 16/16 全 pass 且 `ready=true`；
- 只有产物级校验全部通过后才初始化 MongoDB（`Settings` + `MongoManager.start/initialize`）并
  调用 `V3PersistenceService`；
- 输出只包含状态、schema version、ruleVersion、hash、计数、inserted/existing 等脱敏摘要；
  不输出完整 payload、规则正文、SQL、Mongo URI 或凭据；
- 不新增 API endpoint；模块导入不连接数据库；本任务只实现和测试该脚本，不实际运行。

## 6. 测试设计

- migration：Fake 异步 Database/Collection 覆盖首次执行、重复执行、并发幂等、索引正确性、
  v1-v4 集合与既有数据不变；
- 仓储与服务：沿用 FakeDatabase/FakeCollection 内存模式与 `tests/v3_fixtures.py` 合成 V3 夹具，
  新增合成“ready 交付”夹具（catalog/candidate/result/requests 完整闭包），覆盖首次插入、
  相同内容重放、异内容冲突、输入顺序改变幂等、同 ruleVersion 异 payload 冲突、写前拒绝、
  回读失败与 PyMongo 异常脱敏；
- 脚本：`service_factory` 注入测试替身，覆盖合法产物摘要、非法产物在数据库初始化前失败；
- 默认测试不访问真实 MongoDB、网络、私有目录或密钥；integration 测试更新覆盖 Schema v5 但
  不运行（未获数据库授权）。

## 安全加固与验收修订（2026-09-06，[BUG-20260906-03](BUG-20260906-03-v3-persistence-authorization-and-integrity-gaps.md)）

以下修订不改变第 1-6 节已冻结的数据结构与哈希规则，只收紧迁移授权、产物绑定、错误脱敏与
回读完整性：

### R1 迁移授权分级

- `migrations.py` 固定三个常量：`RUNTIME_SCHEMA_VERSION = 4`、`V3_PERSISTENCE_SCHEMA_VERSION = 5`、
  `LATEST_SCHEMA_VERSION = 5`；
- `apply_migrations(database, *, target_version=RUNTIME_SCHEMA_VERSION)`：target 只允许上述两个
  命名常量，其他值（含 1-3、>5）在任何写入前抛 `ValueError`；只应用 `version <= target` 的
  migration，返回数据库实际生效版本 `max(已有记录版本, target)`（只升不降）；
- 普通 serve、`rule-reader init-db`、V1/V2 parse persistence、V2 handoff、V3 candidate recovery
  走 `MongoManager.initialize()` 默认 v4；仅 `persist_report_release_v3_delivery` 的
  `_persist_via_mongodb` 显式传 `target_version=V3_PERSISTENCE_SCHEMA_VERSION`；数据库已是 v5
  时普通应用正常启动（返回实际版本 5），不降级、不重写 migration 记录；不新增 Settings 开关。

### R2 唯一获批产物绑定（脚本）

- 脚本冻结常量：`APPROVED_DELIVERY_MANIFEST_SHA256 = "0ef3af6939d7cdf9b206bd97d709c58f2308f87af
  625e082f88b03e35d20b0c4"`、`APPROVED_DELIVERY_RULE_VERSION =
  "REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a"`、
  `APPROVED_DELIVERY_REQUEST_COUNT = 18`、`APPROVED_DELIVERY_TEST_CASE_COUNT = 20`；
- 校验顺序：先读 manifest 原始字节并计算 SHA-256 与获批常量比较（信任锚）→ 解析 manifest →
  五个交付文件哈希 → 固定 ruleVersion/requestCount/testCaseCount/ready=true/blocking=0/
  executable=false → 写前闭包；
- 无 `--allow-any`/`--skip-hash`/环境变量绕过；离线测试通过 monkeypatch 上述模块常量构造
  synthetic 成功路径，生产默认值恒为固定身份。

### R3 CLI 错误统一脱敏

- 逐项 request 解析失败 → `V3PersistenceContractError`（cause 保留 ValidationError，消息固定）；
- `MongoStartupError` → `V3PersistenceUnavailableError`；
- `main` 捕获 `V3PersistenceError`，向 stderr 输出 `{"code","message","retryable","details":[]}`
  并以退出码 1 结束；不输出 traceback；message 不含 payload、业务正文、`input_value`、URI、
  凭据或 artifact-dir 绝对路径（错误消息只引用文件名）；
- **配置错误同样脱敏（复核修订）**：`Settings()` 构造抛出的 Pydantic `ValidationError` 转换为
  `V3PersistenceUnavailableError("V3 persistence configuration is invalid")`，cause 保留供内部
  测试；Settings 失败时不得构造 `MongoManager`、不得连接数据库；不得用 `except Exception`
  包住整个持久化流程，转换边界仅覆盖 Settings 构造、Mongo 启动/初始化与已知的稳定应用错误。

### R4 回读完整性

`_parse_stored_batch` / `_parse_stored_wrapper` / `_parse_stored_rule` 加固：

- 解析后先不排序：wrapper 存储顺序必须按 `request_id` 严格升序；顶层 `request_ids` 与 wrapper
  存储顺序逐项相等；request ID 不得重复、factCode 不得重复；
- wrapper `created_at` 必须为 aware UTC 且与 batch `created_at` 相等；rule `stored_at` 必须为
  aware UTC；naive datetime 一律 `V3PersistenceVerificationError`，不再静默补 UTC；
- 顶层 `contract_version`、wrapper `contract_version`、payload `contract_version` 三层一致
  （均须为 `3.0.0`）。

### R5 摘要状态

`delivery_summary`：rule 与 batch 都未新插入 → `existingAndVerified`；rule 本次插入 →
`persistedAndVerified`；rule 已存在而 batch 本次补写 → `recoveredAndVerified`（依靠规则写入
幂等安全恢复的路径）。

### R6 测试与集成

- 新增失败测试先行：迁移分级（默认 v4/显式 v5/非法 target/v5 库上普通启动）、回读乱序/重复
  ID/重复 factCode/时间不一致/naive 时间、脚本未绑定获批身份、CLI 脱敏（畸形 request、缺文件、
  错误 manifest、Mongo 异常）、summary 恢复状态；
- `tests/integration/test_mongodb.py` 与 `test_fact_binding_handoffs_mongodb.py` 更新为：常规
  目标 v4 + 显式 target v5（两个新集合、三个唯一索引、v1-v4 历史不变）+ V3 首写/重放/冲突
  代码路径；本轮不运行（未授权真实数据库）；
- **integration 语义更正（复核修订）**：输入顺序无关性是应用服务语义——由 `V3PersistenceService`
  接收乱序 requests 并经 `prepare_v3_delivery` 统一排序后重放幂等；仓储层接收 wrappers 乱序的
  非法 `PreparedV3HandoffBatch` 必须期待 `V3PersistenceConflictError`，不得把非法 prepared
  record 当作幂等输入。integration 覆盖清单保持：显式 runtime v4、显式 V3 v5、两个新集合与
  三个唯一索引、v1-v4 数据与索引不变、首次插入、相同内容重放、异内容冲突。

### R7 隔离 integration 安全门禁（[BUG-20260906-04](BUG-20260906-04-isolated-mongodb-integration-safety.md)）

- 门禁模块固定为 `tests/integration/mongodb_test_guard.py`，只服务于测试基础设施，不进入
  `src`、不成为生产依赖；导入时不连接数据库。
- 连接信息只从 `os.environ` 读取两个变量：`RULEREADER_TEST_MONGODB_URI` 与
  `RULEREADER_TEST_MONGODB_ALLOW_WRITE`。URI 缺失时明确失败，禁止回退 `Settings().mongodb_uri`
  或 `.env`；写入确认值必须精确等于 `isolated-local-only`，缺失或不等均拒绝，且错误消息不
  回显实际收到的值。
- URI 只允许 `mongodb://` scheme（拒绝 `mongodb+srv`，避免 DNS 解析）；使用 PyMongo 既有
  `parse_uri` 解析主机，不新增依赖；所有节点必须是 `localhost`、`127.0.0.1` 或 `::1`；拒绝
  远程 IP/域名、空 host 与无法解析的 URI；错误消息固定且不含完整 URI、用户名、密码或环境
  变量值（被拒主机名可回显，便于定位）。
- 门禁函数为 `resolve_isolated_test_uri(environ=None)`：纯函数，可注入显式 environ 离线测试；
  全部门禁通过后才返回 URI 供 integration 测试使用；不提供命令行参数、Settings、默认值或
  其他环境变量绕过。
- integration 测试约定：数据库名固定 `rule_reader_test_<uuid>`；`ping` 成功后、任何写入之前
  即武装清理标志；任何中途失败（migration/索引/insert）都会在 `finally` 尝试删除该随机测试
  库；删除前再次断言库名以 `rule_reader_test_` 开头；不枚举、不 glob、不前缀批量删除、不
  使用用户配置的数据库名。
- **拓扑限制（拓扑复核修订）**：仅 nodelist 为 loopback 不足以证明连接停留在本机——
  `replicaSet`/`directConnection=false`/`loadBalanced` 等选项可能触发驱动拓扑发现或多节点
  路由。因此 URI query option 采用严格 allowlist：只允许 `directConnection`、`authSource`、
  `authMechanism`；`directConnection` 必须显式存在且为 `true`（缺失或 false 均拒绝）；
  `replicaSet` 与 `loadBalanced` 无论取值为何都拒绝；其他任何 option 一律拒绝。错误消息不得
  回显完整 URI、凭据、数据库名或 option 的实际值。门禁不修改 `os.environ`、不连接网络、
  不读取 Settings/.env、不新增依赖或生产代码。
