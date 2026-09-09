# RuleReader

RuleReader 当前版本为 `0.12.0`。项目已提供 Python `3.11.9`、FastAPI、MongoDB 基础设施和基于 LangGraph + DeepSeek 的本地文本规则解析模块；真实 Provider 候选无法通过门禁时，只有用户明确授权的离线 `reviewed_import` 才能导入指定候选，且不得冒充 DeepSeek 输出。

新解析结果使用 Schema `2.0.0`，以结构化表达式保留公式、分支、派生事实和日期计算，并由确定性解释器执行测试案例。结果始终是带版本和来源信息的待审核 JSON 草稿，不会发布或执行规则。用户可以显式把草稿归档为不可变 MongoDB 版本；默认试解析不写数据库，归档也不代表已审批。

## 前置条件

- Python `3.11.9`
- 可通过驱动 URI 访问的 MongoDB
- 使用解析功能时需要 DeepSeek API Key、Base URL 和模型 ID

`http://localhost:27017/` 不是 MongoDB 驱动 URI，应使用 `mongodb://...`。

## 安装

PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item -LiteralPath '.env.example' -Destination '.env'
```

也可以直接从 `pyproject.toml` 安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
```

## 配置

所有环境变量使用 `RULEREADER_` 前缀。完整模板见 [.env.example](.env.example)，不要提交包含密钥的 `.env`。

当前 MongoDB 容器启用了认证，需要填写完整连接串：

```dotenv
RULEREADER_MONGODB_URI=mongodb://<username>:<url-encoded-password>@localhost:27017/?authSource=admin
```

解析功能必填：

```dotenv
RULEREADER_DEEPSEEK_API_KEY=<your-key>
RULEREADER_DEEPSEEK_BASE_URL=https://api.deepseek.com
RULEREADER_DEEPSEEK_MODEL=deepseek-v4-flash
```

本地文件 CLI 还需要把文档根目录配置为规则文件所在的受控目录：

```dotenv
RULEREADER_DOCUMENT_ROOT=C:\path\to\rule-documents
```

可调参数包括单条文本字符上限、DeepSeek 超时、重试次数、基础/最大退避、最大输出 token 和进程内幂等缓存容量。检查脱敏配置：

```powershell
.\.venv\Scripts\rule-reader.exe check-config
```

## 初始化数据库与启动服务

```powershell
.\.venv\Scripts\rule-reader.exe init-db
.\.venv\Scripts\rule-reader.exe serve
```

默认地址为 `http://127.0.0.1:8000`，Swagger 位于 `/docs`。健康检查为 `/health/live` 和 `/health/ready`。

普通服务和 `init-db` 的运行时 Schema 为 v4：`rule_versions` 保存 V1/V2 不可变草稿，
`fact_binding_handoffs` 保存 RuleReader 所有、SqlBot 只读的 V2 事实交接，`rule_structure_candidates_v3`
保存不可执行的 V3 恢复候选；`init-db` 可从空库或旧 Schema 幂等升级，但默认只到 v4。代码中已实现
Schema v5 的 `rule_versions_v3` 与 `fact_binding_handoff_batches_v3`，只有显式授权的 V3 持久化
脚本会请求 v5。该脚本已于 2026-09-07 按用户单独授权在本机正式库执行（Schema v5，`rule_versions_v3`
1 条 + 单文档 batch 18 条请求，恢复候选 1 条；证据见 [PROG-20260907](docs/PROG-20260907.md)）。
2026-09-06 换机重建实例的空库快照存于 `generated-rules/mongodb-snapshot-20260906/`（业务集合
0 条、基础设施 5 条文档），仅代表该实例当时状态；文档中的历史记录不构成数据库备份。

## 解析规则文本

HTTP 入口接受一条规则文本：

```powershell
$body = @{
    text = Get-Content -Raw -Encoding utf8 '.\example.md'
    sourceName = 'example.md'
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri 'http://127.0.0.1:8000/api/v1/rules/parse' `
    -Method Post `
    -ContentType 'application/json' `
    -Body $body
```

需要安全重放时可提供 8 至 128 字符的 `Idempotency-Key`。同一服务进程内，相同键与相同解析身份只调用一次 Provider；同键异身份返回 409：

```powershell
Invoke-RestMethod `
    -Uri 'http://127.0.0.1:8000/api/v1/rules/parse' `
    -Method Post `
    -Headers @{ 'Idempotency-Key' = 'parse-request-0001' } `
    -ContentType 'application/json' `
    -Body $body
```

幂等缓存不跨进程、worker 或重启共享；RuleReader 不把该键发送给 DeepSeek，也不记录原始键，只在审计中保留 SHA-256。没有幂等键时，每次请求仍是独立解析。

默认请求只解析。如需同时归档该版本，在请求中显式增加 `persist = $true`：

```powershell
$body = @{
    text = Get-Content -Raw -Encoding utf8 '.\example.md'
    sourceName = 'example.md'
    persist = $true
} | ConvertTo-Json

$parsed = Invoke-RestMethod `
    -Uri 'http://127.0.0.1:8000/api/v1/rules/parse' `
    -Method Post `
    -ContentType 'application/json' `
    -Body $body

$version = [uri]::EscapeDataString($parsed.ruleVersion)
Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/rules/versions/$version" `
    -Method Get

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/rules/versions/$version/fact-binding-requests" `
    -Method Get

```

CLI 入口只允许读取 `RULEREADER_DOCUMENT_ROOT` 内的 Markdown：

```powershell
.\.venv\Scripts\rule-reader.exe parse --file '.\example.md'
```

CLI 也接受进程内幂等键并把其摘要写入调用审计：

```powershell
.\.venv\Scripts\rule-reader.exe parse `
    --file '.\example.md' `
    --idempotency-key 'cli-parse-request-0001'
```

CLI 显式归档：

```powershell
.\.venv\Scripts\rule-reader.exe parse --file '.\example.md' --persist
```

`--persist` 成功时 stdout 仍只有规则 JSON；MongoDB 写入失败时命令返回非零状态和脱敏错误。相同 `ruleVersion` 重复保存不会覆盖已有记录。

已持久化且通过 Schema `2.0.0` 校验的规则可以显式生成 MongoDB 事实交接：

```powershell
.\.venv\Scripts\rule-reader.exe persist-handoffs `
    --rule-version 'REPORT_RELEASE_ALL_001@20260824T080726492666Z-562eabd40e5a'
```

该命令不读取源 Markdown、不调用 DeepSeek，也不修改 `rule_versions`。它先让每条完整 camelCase payload 同时通过 Pydantic、仓库内 Draft 2020-12 Schema 和安全门禁，再写入 `fact_binding_handoffs`。`requestId` 固定为 `<ruleVersion>#<factCode>`；相同哈希重复执行返回幂等成功，不同哈希冲突会失败且不会覆盖首次记录。SqlBot 只能读取该集合，blocking uncertainties 会原样保留。

成功时 stdout 是一个 JSON 文档。主要字段包括：

- `ruleVersion`：规则编号、UTC 时间戳和源内容哈希前缀；
- `status=draft`、`executable=false`；
- `source.sha256`：规范化输入内容 SHA-256；
- `parser.audit`：RuleReader request ID、逐次退避/结果、DeepSeek completion ID、可用 token usage 和幂等键摘要；
- `schemaVersion=2.0.0`：新解析固定使用的新契约；
- `rule.rootCondition`：保留 AND/OR/NOT 和左右表达式比较的 AST；
- `rule.requiredFacts`：包含 `factCode`、事实种类、粒度、参数、空值策略和可选派生表达式；
- `rule.fieldMappings`：字段目录命中仍只是候选；
- `rule.testCases`、失败原因、处理建议和责任角色。

字段映射只允许引用内置的四视图目录。不能确认的字段会明确返回 `mappingStatus=unresolved`，不会猜测。

Schema `1.0.0` 的历史归档保持不可变并可精确回读，但新解析不会再写入该版本，也不能从它导出 Agent 2 请求。事实交接入口只为 Schema `2.0.0` 的非 `derived` 事实生成 camelCase `FactBindingRequest`；请求不包含 SQL、数据库凭据或目标库元数据。

事实交接有独立的契约版本轴。不带参数或显式传入 `contractVersion=2.0.0` 时，入口只返回补齐 `queryRequirements`、来源证据和结构化不确定性的 `FactBindingRequest 2.0.0`；`1.0.0` 与未知版本请求返回 422。查询语义无法从现有规则草稿确定时会保留必填字段、标记 `unresolved` 并给出 `blocking` 项，不会猜测物理字段、聚合或时间条件。阻断项允许草稿保存和审核，但后续 SqlBot 必须在 SQL 候选生成前停止。

可独立验证的 Draft 2020-12 Schema 与样例位于：

- [FactBindingRequest 2.0.0 JSON Schema](contracts/fact-binding-request-2.0.0.schema.json)；
- [合法但显式未决的 2.0.0 样例](contracts/examples/fact-binding-request-2.0.0.valid-unresolved.json)；
- [缺少 timeRange 的非法样例](contracts/examples/fact-binding-request-2.0.0.invalid-missing-time-range.json)；
- [冻结的 1.0.0 兼容样例](contracts/examples/fact-binding-request-1.0.0.legacy.json)。

Schema 和样例由权威 Pydantic 模型确定性导出：

```powershell
.\.venv\Scripts\python.exe -m scripts.export_contract_schemas
```

## Rule Schema 3.0 离线 Slice 1/2

V3 公开交付包含：

- [RuleStructureCandidateV3 JSON Schema](contracts/rule-structure-candidate-3.0.0.schema.json)；
- [BusinessConfirmedFactCatalogV3 JSON Schema](contracts/business-confirmed-fact-catalog-3.0.0.schema.json)；
- [contracts/examples](contracts/examples) 下的脱敏合法/非法样例；
- 确认目录 digest、五阶段顺序、引用闭包、类型、优先级、阻断和多 outcome 的确定性门禁；
- 最多 3 次共享预算、业务缺口早停的显式 LangGraph V3 分支。

V3 不替换生产 Schema `2.0.0` 默认路径。可以完全离线验证公开样例：

```powershell
.\.venv\Scripts\python.exe -m scripts.validate_rule_structure_v3 `
    --catalog contracts/examples/business-confirmed-fact-catalog-3.0.0.valid.json `
    --candidate contracts/examples/rule-structure-candidate-3.0.0.valid.json
```

需要核对外部规则块身份时，可以追加 `--rule-file <path> --rule-set-id <id>`；输出只包含 SHA-256
和字符数，不复制规则正文。真实 Agent 1 单次入口要求显式提供外部规则和确认目录，并带
`--allow-provider`；该命令会把规则文本发送到配置的 DeepSeek：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.run_report_release_agent1_v3_once `
    --rule-file <path> --catalog <confirmed-catalog.json> --allow-provider
```

私有 XLSX 中已填写数据已由用户确认有效；公开仓库只保存读取逻辑、固定哈希和脱敏摘要，视图 SQL、
字段清单、binding profile 和完整业务规则不进入公开仓库。恢复说明见
[BUG-20260905-01](docs/BUG-20260905-01-incomplete-v3-commit.md)。

拥有私有 `RuleDataReferences` 权限时，可验证用户确认的有序 V3 来源。该命令只输出固定身份，不回显
规则、工作簿或 SQL 内容：

```powershell
.\.venv\Scripts\python.exe -m scripts.validate_report_release_v3_reference `
    --reference-root 'D:\path\to\RuleDataReferences'
```

确认固定资料后，可以把 source-bound catalog、候选和恢复 manifest 写入调用方指定的私有目录：

```powershell
.\.venv\Scripts\python.exe -m scripts.report_release_v3_profile `
    --reference-root 'D:\path\to\RuleDataReferences' `
    --output-dir 'D:\path\to\RuleDataReferences-recovery\report-release-v3'
```

该初始恢复命令复现的是 2026-09-05 业务确认前状态：7 个确认事实、5 个阶段、19 个规则节点
（3 active、16 blocked）。它保持 `executable=false`，不调用 Provider、MongoDB 或 SQL；输出目录
应位于固定私有仓库之外，避免改变 bundle 的受管文件集合和 digest。

用户明确选择恢复到当前 MongoDB 时，执行：

```powershell
.\.venv\Scripts\python.exe -m scripts.persist_report_release_v3_recovery `
    --reference-root 'D:\path\to\RuleDataReferences'
```

该命令先重建并验证同一 source-bound payload，再升级到 MongoDB Schema v4，向
`rule_structure_candidates_v3` insert-only 保存并精确回读。它不会写入 `rule_versions` 或
`fact_binding_handoffs`，也不会把 blocking 候选变成规则版本、事实交接或可执行对象。

## V3 Agent 2 readiness

有序 V3 与 V2 remediation 不满足语义等价门禁，因此不能恢复旧 V2 作为 SqlBot 输入。以下命令
离线复现业务确认前的脱敏差异、确认清单和 MongoDB 待落库计划：

```powershell
.\.venv\Scripts\python.exe -m scripts.analyze_v3_agent2_readiness `
    --reference-root 'D:\path\to\RuleDataReferences' `
    --output-dir 'D:\path\to\RuleDataReferences-recovery\agent2-readiness'
```

16 项 blocking 已于 2026-09-06 完成业务确认。使用固定时间戳可以确定性重建当前 confirmed 产物：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.report_release_v3_confirmed_profile `
    --reference-root 'D:\path\to\RuleDataReferences' `
    --output-dir 'D:\path\to\RuleDataReferences-recovery\report-release-v3-confirmed' `
    --generated-at '2026-09-05T17:24:07+00:00'
```

当前结果包含一个 `RuleParseResultV3`、18 条 `FactBindingRequest 3.0.0`，16 条 readiness 门禁全部
通过（`ready=true`）。所有产物仍为待审核、`executable=false`、mapping unresolved；尚未写入
MongoDB。当前 SqlBot 只消费 2.0.0，必须在其仓库另行升级后才能接收 3.0.0。上述命令不访问
MongoDB、DeepSeek 或 SQL Server。

## V3 交付的 Schema v5 持久化（显式授权执行）

MongoDB Schema v5 已按 [REQ-20260906-01](docs/REQ-20260906-01-v3-mongodb-persistence.md) 实现：
`rule_versions_v3` 保存一个完整、不可变、待审核、`executable=false` 的 `RuleParseResultV3`，
`fact_binding_handoff_batches_v3` 把一个 ruleVersion 的全部请求 wrapper（含完整 camelCase
payload 与 canonical hash）保存为一个单文档 batch。两条链路均为 insert-only：相同内容重复执行
幂等并保留首次时间，不同内容哈希冲突失败且不覆盖；任何写入前先完成 blocking、readiness 16/16、
hash 闭包、请求身份与数量门禁，写入后精确回读并复核历史集合数量不变。

在用户明确授权向真实 MongoDB 写入后，可执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.persist_report_release_v3_delivery `
    --artifact-dir 'D:\path\to\RuleDataReferences-recovery\report-release-v3-confirmed'
```

该命令先校验 manifest 文件自身 SHA-256 是否等于仓库内冻结的获批交付身份（信任锚），再做 Pydantic
解析、manifest 内记录的五个交付文件 SHA-256、固定 ruleVersion/requestCount/testCaseCount、
readiness 16/16 与写前闭包门禁校验，全部通过后才初始化 MongoDB（显式请求 Schema v5）并调用
持久化服务；stdout 只输出状态、schema version、ruleVersion、哈希、计数和 inserted/existing 等
脱敏摘要，不输出规则正文、SQL、Mongo URI 或凭据。任何 synthetic、自签名或再生 manifest 的产物
会被拒绝，也没有绕过参数或环境开关。普通服务与 `init-db` 不受该脚本影响，运行时 Schema 默认
停留在 v4。该脚本已于 2026-09-07 按用户单独授权对真实 MongoDB 执行并完成回读复核
（`persistedAndVerified`，证据见 [PROG-20260907](docs/PROG-20260907.md)）；重复执行幂等重放，
不会覆盖已有记录。

## 业务审核修订草稿的离线导出

[REQ-20260827-01](docs/REQ-20260827-01-schema2-business-review-remediation.md) 的项目报告释放修订 profile 只能用模块方式执行本地校验和导出：

```powershell
.\.venv\Scripts\python.exe -m scripts.export_reviewed_report_release_remediation `
    --document-root 'C:\path\to\authorized-rule-directory' `
    --source '项目报告释放规则.md' `
    --generated-at '2026-08-27T01:32:25.952760Z' `
    --output-dir '.\artifacts\report-release-all-001-remediation'
```

该命令绑定已授权来源哈希，只输出 `validated_not_persisted` 的规则与事实请求 JSON。它不加载应用 Settings、不连接 MongoDB、不调用 DeepSeek，也没有持久化参数；导出通过不代表业务批准、发布或可执行。是否持久化新版本必须在业务复审通过后另行授权。

RuleReader 只负责 Agent 1 规则理解和事实请求导出。SQL Server 元数据组合、DeepSeek SQL 候选生成、SQL AST、安全校验和审核属于独立的 SqlBot（Agent 2）阶段。

## 私有参考资料

项目外的字段映射、视图定义、规则原文和设计文档已收拢到私有
[colglaze/RuleDataReferences](https://github.com/colglaze/RuleDataReferences) 的固定 bundle：

- Bundle：`PROJECT_RELEASE_REFERENCE_20260901_001`；
- Commit：`2240e5bd18e36d17650896a10cc61e1c18e3daa0`；
- Content digest：`6d403f1a110ea1699a72aec76f38be944583670f96767f5e3f44b2ac2e565160`。

这些资料固定 `authority=none`、`executable=false`，不进入 RuleReader 运行时，不覆盖已持久化规则，
也不授权 SqlBot 创建元数据 grant、清除 blocking uncertainty 或生成/执行 SQL。公开仓库不复制内部
字段清单或完整视图 SQL。

## 验证

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe
.\.venv\Scripts\pytest.exe
.\.venv\Scripts\pytest.exe -m integration
.\.venv\Scripts\pytest.exe -m provider_integration
```

默认测试不访问 MongoDB 或 DeepSeek。MongoDB 和 Provider 测试必须显式选择，并分别读取已配置的本地凭据。

MongoDB integration 测试有独立的安全门禁（`tests/integration/mongodb_test_guard.py`，纯测试
侧模块）：必须显式设置 `RULEREADER_TEST_MONGODB_URI`（仅 `mongodb://` scheme，所有主机必须为
localhost/127.0.0.1/::1，必须包含 `directConnection=true`，query option 只允许
`directConnection`/`authSource`/`authMechanism`，拒绝 `mongodb+srv`、`replicaSet`、
`loadBalanced`、远程主机与任何其他选项），并显式设置
`RULEREADER_TEST_MONGODB_ALLOW_WRITE=isolated-local-only` 确认写入；缺失或回退
`Settings().mongodb_uri` 一律失败。URI 形态示意（占位符，非真实凭据）：

```dotenv
RULEREADER_TEST_MONGODB_URI=mongodb://<user>:<password>@localhost:<port>/?authSource=<auth-db>&directConnection=true
RULEREADER_TEST_MONGODB_ALLOW_WRITE=isolated-local-only
```

满足门禁后测试只对随机 `rule_reader_test_<uuid>` 数据库
读写，并在 `finally` 中删除该库（含 migration 中途失败的场景）。
