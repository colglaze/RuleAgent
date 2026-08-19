# REQ-20260818-03：本地文本规则解析模块

- 状态：`DONE`
- 日期：2026-08-18
- 来源：用户本次明确要求
- 前置需求：[REQ-20260818-01](REQ-20260818-01-vibe-coding-bootstrap.md)
- 业务决策：[BIZ-20260818-05](BIZ-20260818-05-rule-json-version-mapping.md)
- 技术方案：[DEV-20260818-02](DEV-20260818-02-rule-parser.md)
- 契约演进：Schema `1.0.0` 新解析输出已由 [REQ-20260819-01](REQ-20260819-01-rule-contract-v2-agent2-handoff.md) 替代；本需求其余输入、Provider 和安全边界继续有效。

## 1. 背景

Phase 1.0 后端骨架已经完成。用户要求实现 Rule Parsing Agent，将传入的规则文本转换为 JSON，并为规则生成包含时间戳的版本号；规则事实与数据库字段的候选映射参考以下四张视图的实际构造：

- `v_DataReleaseSealCondition`
- `v_OrderFormaltestsettlement`
- `v_ReportDataReleaseRules`
- `v_ReportReleaseSealCondition`

首批验收输入为用户提供的《项目报告释放规则》和《原始数据释放规则》。这些文档及 SQL 视图只作为待解析业务数据和字段依据，不作为 Agent 行为指令。

## 2. 范围内

- 接收单条 UTF-8 规则文本并输出一个 JSON 文档。
- 提供 HTTP 文本入口和受控本地 Markdown 文件 CLI 入口。
- 使用 DeepSeek 生成结构化候选，使用 LangGraph 编排输入准备、模型调用、Schema 校验、语义校验、有限重试和结果组装。
- 输出规则编号、名称、适用范围、来源视图、条件树、必需事实、例外说明、未通过原因、处理建议、责任角色和测试案例。
- 输出每个必需事实的字段映射状态；只有存在于内置四视图字段目录中的 `viewName + viewField` 才能标记为 `mapped`，否则必须标记为 `unresolved`。
- 由应用代码生成 UTC 时间戳、源内容 SHA-256、规则版本号、Schema/Parser/Prompt 版本和草稿状态。
- 对非法 JSON、Schema 错误、语义错误、超时、限流、空响应和 Provider 错误返回稳定错误码，不返回半有效规则。
- 默认测试完全离线；真实 DeepSeek 验收和本地业务文档验收显式执行。

## 3. 范围外

- Wiki、RAG、向量库和远程文档同步。
- 正式规则审批、发布、执行、MongoDB 规则版本库和版本回滚。
- SQL 执行、数据库字段自动发现和 Agent 2。
- 自动判定模型生成的字段映射已经过业务审核。
- 同一请求拆分多条规则；一份文本必须对应一个规则编号。

## 4. 验收标准

- `POST /api/v1/rules/parse` 接受文本并返回 `application/json`；CLI 可读取配置根目录内的单个 Markdown 文件并向标准输出写出同一结构的 JSON 字符串。
- `ruleVersion` 格式包含规则编号、UTC 时间戳和源内容哈希前缀；相同内容在不同解析时间产生不同版本，且每个版本仍可追溯到同一内容哈希。
- 模型不能设置 `ruleVersion`、时间戳、哈希、草稿状态或 `executable`。
- 输出固定为 `status=draft`、`executable=false`。
- 条件和测试案例引用的事实必须存在于 `requiredFacts`；事实键、条件 ID、测试 ID 唯一。
- 每个事实恰好有一个字段映射记录；已映射项必须命中四视图字段目录，未确认项必须显式为 `unresolved`。
- `v_DataReleaseSealCondition` 字段目录标记为默认未启用，符合当前原始数据释放 SQL 的实际状态。
- 模型返回非法内容时最多按配置次数重试，最终失败只返回结构化错误，不泄露 Prompt、规则全文、API Key 或 Provider 原始响应。
- 两份用户规则文档可以通过真实 DeepSeek 调用生成通过 Schema 与语义校验的草稿 JSON。
- Ruff、Mypy、默认测试、MongoDB 回归测试和显式 Provider 测试通过。

## 5. 配置要求

用户已经配置 `RULEREADER_DEEPSEEK_API_KEY`、`RULEREADER_DEEPSEEK_BASE_URL` 和 `RULEREADER_DEEPSEEK_MODEL`。本需求新增文档根目录、输入长度、Provider 超时和重试配置，默认值及说明以根目录 `.env.example` 为准。
