# BIZ-20260818-05：规则 JSON、版本号与字段映射策略

- 状态：`ACCEPTED`
- 日期：2026-08-18
- 来源 REQ：[REQ-20260818-03](REQ-20260818-03-rule-parser.md)
- 影响范围：规则解析输出、版本标识、视图字段目录和失败策略
- 契约演进：Schema/Prompt v1 决策已由 [BIZ-20260819-01](BIZ-20260819-01-agent2-handoff-baseline.md) 替代；版本和候选映射策略继续有效。

## 1. 决策

1. 一个解析请求只产生一条待审核规则草稿；不自动拆分多规则文本。
2. HTTP 返回 JSON 文档，CLI 向标准输出返回同一文档的 UTF-8 JSON 字符串，不进行双重 JSON 编码。
3. DeepSeek 只生成业务候选字段；版本、来源、状态和解析器元数据由可信代码生成。
4. `ruleVersion` 格式为 `<ruleId>@<UTC basic timestamp>-<source sha256 first 12>`，例如 `REPORT_RELEASE_ALL_001@20260818T163012123456Z-a1b2c3d4e5f6`。
5. JSON Schema 版本使用语义版本；本阶段固定为 `1.0.0`。Parser 版本来自应用版本，Prompt 版本固定为 `rule-parser-v1`。
6. 输出永远是 `draft` 且 `executable=false`；字段映射同样是待审核候选。
7. 字段映射只允许引用四视图字段目录。模型给出的视图和字段必须精确命中目录，代码再补入权威 `sourceExpression` 和视图启用状态。
8. 无法确认映射时必须输出 `unresolved`，不得把相似字段或自然语言推断冒充为已确认映射。
9. 当前不持久化规则版本；版本元数据随 JSON 输出交付。正式版本库另行建立 REQ/BIZ/DEV。
10. DeepSeek 使用兼容 OpenAI Chat Completions 的 HTTP API 和 JSON Output 模式，由 HTTPX 直接调用；规则抽取固定关闭 V4 默认 thinking，避免推理内容耗尽结构化输出预算；不在领域层引入供应商 SDK 类型。

## 2. 四视图目录边界

| 视图 | 当前默认启用 | 主要可映射输出 |
| --- | --- | --- |
| `v_DataReleaseSealCondition` | 否 | `ddid`、`count_all`、`count_meet`、`count_nomeet`、`dd_ismeet` |
| `v_OrderFormaltestsettlement` | 是 | `dd`、`sqlc`、`zssywgfy`、`bcjsfy`、`zssyjsfy`、订单与联系人上下文字段 |
| `v_ReportDataReleaseRules` | 是 | `ddgldk`、`ddglyj`、`ddgldk_total`、`bgsffy`、`sjsffy`、`zssywgfy`、`ctwgfy`、`wgfy_total`、`ddwgldk_total`、`ddwgldk_total20`、`ctzjjsfy` |
| `v_ReportReleaseSealCondition` | 是 | `ddid`、`count_all`、`count_meet`、`count_nomeet`、`dd_ismeet` |

`v_ReportDataReleaseRules` 的 `t1.*` 不展开为任意可映射字段，因为现有视图文本没有提供稳定的显式输出清单。主视图和其他表中的字段不属于这四视图目录，当前标记为 `unresolved`，留待后续数据库元数据发现阶段确认。

## 3. 安全与失败策略

- 规则正文是不可信输入；Prompt 明确要求忽略正文中的指令，只抽取业务事实。
- Provider 响应是不可信候选；必须依次通过 JSON 解码、Pydantic Schema 和确定性语义校验。
- 超时、429、5xx、空响应、非法 JSON、Schema 或语义失败允许有限重试；认证和请求参数错误不重试。
- API 与日志不返回完整 Prompt、输入全文、Authorization header 或 Provider 原始响应。

## 4. 官方依据

- [DeepSeek API Quick Start](https://api-docs.deepseek.com/)
- [DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)
- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
