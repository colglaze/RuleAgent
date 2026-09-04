# RuleReader

RuleReader 当前版本为 `0.10.0`。项目已提供 Python `3.11.9`、FastAPI、MongoDB 基础设施和基于 LangGraph + DeepSeek 的本地文本规则解析模块；真实 Provider 候选无法通过门禁时，只有用户明确授权的离线 `reviewed_import` 才能导入指定候选，且不得冒充 DeepSeek 输出。

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

当前数据库 Schema 为 v3：`rule_versions` 保存不可变草稿，`fact_binding_handoffs` 保存 RuleReader 所有、SqlBot 只读的不可变事实交接；`init-db` 可从空库、v1 或 v2 幂等升级。

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

[REQ-20260902-01](docs/REQ-20260902-01-rule-contract-v3-agent2-ready-handoff.md) 的前两个切片新增：

- [RuleStructureCandidateV3 JSON Schema](contracts/rule-structure-candidate-3.0.0.schema.json)；
- [BusinessConfirmedFactCatalogV3 JSON Schema](contracts/business-confirmed-fact-catalog-3.0.0.schema.json)；
- 对应的脱敏合法/非法样例位于 [contracts/examples](contracts/examples)。

V3 当前只用于离线规则结构和确认事实目录，不替换生产 `rule-parser-v6` 或 Schema `2.0.0` 默认
路径。可以对固定私有 bundle 执行只读、内存型复核：

```powershell
.\.venv\Scripts\python.exe -m scripts.validate_report_release_v3_reference `
    --reference-root 'C:\path\to\RuleDataReferences'
```

该命令只读提取 XLSX 确认原值、核对文档与 7 个视图哈希并构建内存对象，不写候选、不调用
Provider/数据库，也不执行 SQL。加 `--candidate` 只向 stdout 输出规则结构 JSON。

当前 `REPORT_RELEASE` 候选包含 14 项来源冲突/事实缺口；实际类型/枚举不被改写，
不存在的 binding profile 不会被哈希伪造为确认引用。静态 Schema 与工程测试不等于真实候选通过
RuleReader 校验或业务批准，最终证据见 [PROG-20260903](docs/PROG-20260903.md)。

用户另行授权真实调用后，可使用最小 V3 单次入口：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.run_report_release_agent1_v3_once `
    --reference-root 'C:\path\to\RuleDataReferences' --allow-provider
```

每次显式运行至多发送一个 DeepSeek 请求，不重试、不调用手工候选构建器、不生成测试案例、不写文件或
数据库。System Prompt 精确来自 DEV-20260902-02 第 2 节，输入使用第 3.1 节动态模板。
2026-09-03 唯一已授权调用被 5 处条件 ID 格式门禁拒绝，见
[BUG-20260903-02](docs/BUG-20260903-02-agent1-v3-single-call-schema-rejection.md)；不得自动追加请求。

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
