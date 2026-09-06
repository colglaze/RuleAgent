# REQ-20260906-01：V3 交付 MongoDB Schema v5 持久化

- 状态：`IMPLEMENTED_OFFLINE_AWAITING_REAL_WRITE_AUTHORIZATION`
- 日期：2026-09-06
- 来源需求：[REQ-20260905-02](REQ-20260905-02-v3-agent2-handoff-readiness.md)
- 业务决策：[BIZ-20260906-02](BIZ-20260906-02-v3-mongodb-persistence.md)
- 前置决策：[BIZ-20260905-02](BIZ-20260905-02-v3-agent2-handoff-contract.md)、
  [BIZ-20260906-01](BIZ-20260906-01-v3-blocker-business-confirmation.md)
- 技术方案：[DEV-20260906-02](DEV-20260906-02-v3-mongodb-persistence.md)
- 前置缺陷修复：[BUG-20260906-02](BUG-20260906-02-confirmed-profile-version-coupling.md)

## 范围

用户已明确授权完成“RuleReader MongoDB Schema v5 持久化”的代码、自动化测试和文档同步，并允许把
应用版本升级到 `0.12.0`。本需求冻结以下交付：

1. MongoDB Schema v5 migration：新增且仅新增 `rule_versions_v3` 与
   `fact_binding_handoff_batches_v3` 两个集合及其唯一索引；migration 幂等、支持并发初始化、
   fail-fast，不修改任何历史集合与历史记录。
2. V3 持久化应用层与 MongoDB 适配器：服务接收 `BusinessConfirmedFactCatalogV3`、
   `RuleStructureCandidateV3`、`RuleParseResultV3` 与全部 `FactBindingRequestV3`；写入前一次性
   完成全部门禁，写入后精确回读并重新校验；insert-only、同 hash 幂等、异 hash 冲突。
3. 显式离线脚本 `scripts/persist_report_release_v3_delivery.py`：从 `--artifact-dir` 读取并校验
   confirmed V3 产物，全部校验通过后才初始化 MongoDB 并调用持久化服务；输出脱敏摘要。
4. confirmed reviewed-import profile 的 parserVersion 与应用包版本解耦（见
   [BUG-20260906-02](BUG-20260906-02-confirmed-profile-version-coupling.md)），冻结为 `0.11.0`，
   不改变任何既有产物身份。
5. 应用版本升级到 `0.12.0` 并同步所有直接绑定的测试期望与文档。

## 非目标（本需求明确排除）

- 执行真实持久化命令、向当前真实 MongoDB 写入数据；
- 调用 DeepSeek、连接 SQL Server、生成或执行 SQL；
- 修改 SqlBot 或其他仓库；
- 提交、推送、创建分支或 PR；
- 新增 HTTP API endpoint、第三个集合、事务、消息队列或额外抽象；
- 修改 V1/V2 schema 或语义、修改现有 `rule_versions`、`fact_binding_handoffs`、
  `rule_structure_candidates_v3` 数据模型、修改 Rule Schema 3.0 / FBR 3.0.0 契约含义；
- 把 mapping unresolved 改成 mapped、`executable=false` 改成 `true`、`draft` 改成
  approved/published。

## 数据结构验收标准

- `rule_versions_v3`：`_id = ruleVersion`；至少包含 `rule_version`、`rule_set_id`、
  `schema_version="3.0.0"`、`source_sha256`、`catalog_digest`、`candidate_payload_sha256`、
  `payload_sha256`、`status="draft"`、`executable=false`、`stored_at` 与 `payload`
  （`RuleParseResultV3` 完整 camelCase JSON）。
- `fact_binding_handoff_batches_v3`：一个 ruleVersion 只保存一个单文档 batch；`_id = ruleVersion`；
  至少包含 `rule_version`、`contract_version="3.0.0"`、`request_count`、`request_ids`、
  `batch_sha256`、`created_at` 与 `requests`（全部请求 wrapper：`request_id`、`rule_version`、
  `fact_code`、`contract_version`、`payload_sha256`、`created_at`、`payload`）。

## 行为验收标准

- canonical hash 规则：UTF-8、`sort_keys=True`、紧凑 JSON separators、`ensure_ascii=False`、
  禁止 NaN；时间字段不进入 payload/batch hash；requests 计算 batch hash 与保存前按 `requestId`
  确定性排序。
- 保存规则：insert-only；相同 identity + 相同 canonical hash 幂等返回原记录并保留首次时间；
  相同 identity + 不同 hash 返回稳定、脱敏的冲突错误；PyMongo 错误转换为不泄露 URI、凭据、完整
  业务正文或原始 payload 的应用错误。
- 写前门禁一次性完成：candidate 0 blocking；result draft 且 `executable=false`；
  `agent2ReadinessReady=true`；16 条 readiness gate 全部 pass；result 的 source/catalog/candidate
  hash 闭包有效；request 数量与非派生 fact declaration 一致；每个 fact 正好一条 request；
  requestId/ruleVersion/factCode/contractVersion 全部闭包；无重复 request ID/factCode；request
  payload hash 和 batch hash 有效。任一门禁失败时零写入。
- 回读门禁：规则文档与 batch 可重新 Pydantic 解析；wrapper identity 与 payload 一致；canonical
  hash、数量、request ID 集合和 ruleVersion 闭包一致；原有三个集合的文档数量前后不变。
- 规则文档和 batch 是两个不可变文档；batch 原子性只依赖“所有 request 位于单个 MongoDB 文档”。
  规则已写入而 batch 暂时失败时，重试必须依靠规则写入幂等安全恢复。

## 测试验收标准

- Schema v5 migration 首次执行、重复执行、并发幂等；两个集合与三个唯一索引正确；v1-v4 集合与
  已有数据不变。
- V3 rule 与 batch 的首次插入、相同内容重放、异内容冲突、输入顺序改变仍幂等、同 ruleVersion 异
  request payload 冲突不覆盖均有测试。
- 重复/缺失/多余 request、错误 requestId、错误 ruleRef、blocking、readiness=false、非 16/16 pass
  被写前拒绝且零写入。
- 损坏 wrapper、错误 hash、错误数量、错误时区在回读时失败；MongoDB 异常转换为稳定脱敏错误。
- 默认测试不访问真实 MongoDB、网络、私有目录或密钥；真实 Provider 测试显式启用。
- integration 测试可更新以覆盖 Schema v5，但未获明确数据库授权前不运行。

## 完成标准

- 上述验收全部有自动化测试或可重复命令证据；`docs/进度文档.md` 与当日 `PROG` 记录实际命令、
  结果、未运行项、遗留问题与下一任务。
- 真实 MongoDB 写入仍需用户单独授权；本需求完成不等于任何真实写入已发生。

## 验收修订（2026-09-06，[BUG-20260906-03](BUG-20260906-03-v3-persistence-authorization-and-integrity-gaps.md)）

以下修订不改写上文原始范围，只收紧授权门禁与完整性校验：

1. **Schema 版本分级**：普通服务启动、`rule-reader init-db`、V1/V2 parse persistence、V2
   handoff、V3 candidate recovery 默认只迁移到 `RUNTIME_SCHEMA_VERSION=4`；仅
   `persist_report_release_v3_delivery` 在全部离线产物校验通过后显式请求
   `V3_PERSISTENCE_SCHEMA_VERSION=5`；`apply_migrations` 必须接收显式 `target_version`；数据库
   已是 v5 时普通应用正常启动，不降级、不重写；非法或超出支持的 target 在任何写入前失败；
   不新增 Settings 开关。
2. **唯一获批产物绑定**：脚本在信任 manifest 内容前先校验 manifest 文件自身 SHA-256 等于固定
   常量 `0ef3af6939d7cdf9b206bd97d709c58f2308f87af625e082f88b03e35d20b0c4`，再校验 manifest 记录
   的五个交付文件哈希，并校验固定 ruleVersion
   `REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a`、
   requestCount=18、testCaseCount=20、ready=true、blocking=0、executable=false；synthetic、
   自签名或再生 manifest 一律拒绝；不提供 `--allow-any`、`--skip-hash`、环境变量绕过或测试
   专用生产参数；默认测试不依赖私有目录，可 monkeypatch 脚本常量构造 synthetic 成功路径。
3. **CLI 错误脱敏**：畸形 request 的 Pydantic 错误转换为稳定 `V3PersistenceContractError`；
   `MongoStartupError` 与持久化错误转换为稳定 `V3PersistenceError` 子类；`main` 向 stderr 输出
   最小 JSON（code/message/retryable/details=[]），非零退出，无 traceback，不包含 payload、
   业务正文、`input_value`、URI、凭据或 artifact-dir 绝对路径。
4. **回读加固**：存量 requests wrapper 必须已按 request_id 严格升序；`request_ids` 与存储顺序
   逐项一致；request ID 与 factCode 不得重复；wrapper `created_at` 为 aware UTC 且等于 batch
   `created_at`；rule `stored_at` 为 aware UTC，不静默补时区；三层 contractVersion 一致。
5. **摘要状态**：rule 或 batch 任一本次新插入即不得报告 `existingAndVerified`；新增
   `recoveredAndVerified` 表示规则已存在、batch 本次补写。
