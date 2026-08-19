# RuleReader

RuleReader 当前版本为 `0.4.0`。项目已提供 Python `3.11.9`、FastAPI、MongoDB 基础设施和基于 LangGraph + DeepSeek 的本地文本规则解析模块。

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

可调参数包括单条文本字符上限、DeepSeek 超时、重试次数和最大输出 token。检查脱敏配置：

```powershell
.\.venv\Scripts\rule-reader.exe check-config
```

## 初始化数据库与启动服务

```powershell
.\.venv\Scripts\rule-reader.exe init-db
.\.venv\Scripts\rule-reader.exe serve
```

默认地址为 `http://127.0.0.1:8000`，Swagger 位于 `/docs`。健康检查为 `/health/live` 和 `/health/ready`。

当前数据库 Schema 为 v2，新增 `rule_versions` 不可变草稿集合；`init-db` 可从空库或 v1 幂等升级。

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

CLI 显式归档：

```powershell
.\.venv\Scripts\rule-reader.exe parse --file '.\example.md' --persist
```

`--persist` 成功时 stdout 仍只有规则 JSON；MongoDB 写入失败时命令返回非零状态和脱敏错误。相同 `ruleVersion` 重复保存不会覆盖已有记录。

成功时 stdout 是一个 JSON 文档。主要字段包括：

- `ruleVersion`：规则编号、UTC 时间戳和源内容哈希前缀；
- `status=draft`、`executable=false`；
- `source.sha256`：规范化输入内容 SHA-256；
- `schemaVersion=2.0.0`：新解析固定使用的新契约；
- `rule.rootCondition`：保留 AND/OR/NOT 和左右表达式比较的 AST；
- `rule.requiredFacts`：包含 `factCode`、事实种类、粒度、参数、空值策略和可选派生表达式；
- `rule.fieldMappings`：字段目录命中仍只是候选；
- `rule.testCases`、失败原因、处理建议和责任角色。

字段映射只允许引用内置的四视图目录。不能确认的字段会明确返回 `mappingStatus=unresolved`，不会猜测。

Schema `1.0.0` 的历史归档保持不可变并可精确回读，但新解析不会再写入该版本，也不能从它导出 Agent 2 请求。事实交接入口只为 Schema `2.0.0` 的非 `derived` 事实生成 camelCase `FactBindingRequest`；请求不包含 SQL、数据库凭据或目标库元数据。

RuleReader 只负责 Agent 1 规则理解和事实请求导出。SQL Server 元数据组合、DeepSeek SQL 候选生成、SQL AST、安全校验和审核属于独立的 SqlBot（Agent 2）阶段。

## 验证

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe
.\.venv\Scripts\pytest.exe
.\.venv\Scripts\pytest.exe -m integration
.\.venv\Scripts\pytest.exe -m provider_integration
```

默认测试不访问 MongoDB 或 DeepSeek。MongoDB 和 Provider 测试必须显式选择，并分别读取已配置的本地凭据。
