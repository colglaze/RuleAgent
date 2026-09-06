# BUG-20260905-01：65a9684 缺失 V3 交付文件

- 状态：`FIXED_PUBLIC_ARTIFACTS_RECONSTRUCTED`
- 发现日期：2026-09-05
- 来源需求：[REQ-20260902-01](REQ-20260902-01-rule-contract-v3-agent2-ready-handoff.md)；原文件
  未入库，本次依据提交内可达设计及用户提供规则和当前补齐授权重建。
- 进度：[PROG-20260905](PROG-20260905.md)

## 复现与影响

在 `65a96846b3ae991b42a8159dbbee43a9bbe15846` 的干净克隆中，按锁文件安装依赖，使用 Python 3.11.9 运行
`python -m pytest -q`，得到 16 个收集错误，首个错误是缺少 `rule_reader.domain.rules.catalog_v3`。
运行契约导出同样失败。V2 应用入口也通过包初始化间接依赖这个缺失模块。

Git 当前树、分支及不可达对象检查没有发现可恢复原件。本机 2026-09-03 会话也不包含该仓库补丁。
因此以下公开内容按提交内仍可达的 PRD、技术设计、实施与进度摘要重建，而不是冒充原始字节恢复。

## 已恢复公开交付

- 领域模型：`catalog_v3.py`、`v3.py`、`validation_v3.py`。
- 应用能力：`source_v3.py`、`prompt_v3.py`、`workflow_v3.py`，以及 DeepSeek 显式 V3 方法。
- 脱敏夹具和回归：`tests/v3_fixtures.py`、V3 领域/工作流/Provider 测试、公开产物重建测试。
- 脚本：通用离线 `validate_rule_structure_v3.py` 和显式单次 Provider
  `run_report_release_agent1_v3_once.py`。
- Schema：`contracts/business-confirmed-fact-catalog-3.0.0.schema.json`、
  `contracts/rule-structure-candidate-3.0.0.schema.json`。
- 样例：`contracts/examples/` 下的 `business-confirmed-fact-catalog-3.0.0.valid.json`、
  `business-confirmed-fact-catalog-3.0.0.invalid-missing-digest.json`、
  `rule-structure-candidate-3.0.0.valid.json`、`rule-structure-candidate-3.0.0.invalid-missing-default.json`。
- 重建的决策与进度文档：
  - `REQ-20260902-01-rule-contract-v3-agent2-ready-handoff.md`
  - `BIZ-20260902-01-rule-v3-agent2-ready-boundary.md`
  - `DEV-20260902-01-rule-contract-v3-agent2-ready-handoff.md`
  - `DEV-20260902-02-agent1-v3-prompt.md`
  - `BUG-20260902-01-latest-rule-agent1-semantic-rejection.md`
  - `BUG-20260903-01-v3-confirmation-and-validation-gaps.md`
  - `BUG-20260903-02-agent1-v3-single-call-schema-rejection.md`
  - `PROG-20260902.md`
  - `PROG-20260903.md`

## 私有资料与公开实现边界

`report_release_v3_profile.py` 和 `validate_report_release_v3_reference.py` 已恢复为 source-bound
读取器：公开代码只保存固定身份、工作簿坐标、逻辑 factCode 和确定性门禁；私有 bundle、XLSX、
视图 SQL、内部字段和完整规则仍只保留在 RuleDataReferences。profile 只把 catalog/candidate 写入调用
方指定目录，不接入运行时、Provider、MongoDB 或 SQL。

用户提供的完整规则只在原附件中读取。已验证唯一规则块身份为 SHA-256
`f9d7187d5c1b545cdcc1fbf075dcd126bc26f91a5b6737d16d5e6adb5d98e307`、6,136 字符；正文没有写入
RuleReader。该规则可以作为 Agent 1 输入，但不能替代业务确认事实目录或 binding profile。

## 验收与遗留

- 默认离线测试、Ruff、格式、严格 Mypy、依赖检查与 `git diff --check` 必须全部通过；最终命令和
  数量记录在 [PROG-20260905](PROG-20260905.md)。
- 回归测试在临时目录重建全部公开契约，逐一与仓库 JSON 比较，并验证重复导出字节一致。
- 历史 142/203/204 项测试、真实调用次数和候选事实数量仍只作为重建来源摘要，不作为本次证据。
- 用户已确认 XLSX 填写值有效，并指定第 1.3 节有序规则为 V3 权威结构来源。恢复结果为 7 个确认
  事实、19 个规则节点、16 个 blocking 节点；仍缺的事实与来源编码冲突不猜测。
