# BIZ-20260920-01：项目报告释放规则公式树 V3 重解析裁决

- 状态：`APPROVED_OFFLINE_FORMULA_PARSE`
- 日期：2026-09-20
- 来源需求：[REQ-20260902-01](REQ-20260902-01-rule-contract-v3-agent2-ready-handoff.md)、
  [REQ-20260905-02](REQ-20260905-02-v3-agent2-handoff-readiness.md)
- 关联设计：[DEV-20260920-01](DEV-20260920-01-report-release-formula-v3.md)
- 被替代决策：[BIZ-20260906-01](BIZ-20260906-01-v3-blocker-business-confirmation.md)
  第 3 条（线下/批量释放标志以工作簿 `{4, 5}` 写入 active when）**仅对本次新解析生效**；
  既有 MongoDB 版本
  `REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a`
  必须原样保留，不得覆盖。

## 用户拍板（2026-09-20）

1. 权威文本为优化方案全文（SHA-256
   `c049af189fc3689bac8e96408d9e7239a8c70b66bbcd15829e509c6d524b648f`）。选择原因是该文档有顺序执行。
2. 暂时不导入原始数据释放规则（D0–D4、数据侧前提、`evaluateDataRules`、`DataReleaseRule` 全部排除）。
3. 本执行者不负责 SqlBot 生成完整视图式 SQL。
4. 旧 MongoDB 版本、旧 source/ruleBlock SHA-256
   `f285643e5b2bb2ec7b13861716407afda4252c2fbc81eb75a4b0bb3ba4b37c6d`
   与旧 `batchSha256`
   `0df35b3597aae0d3e9d06262af76086813da492e49169b99e933cc49a3628c3e`
   必须保留。新结果必须是新的 `sourceSha256`、`catalogDigest`、`ruleVersion`、handoff batch。

## 同文档冲突解释顺序

1. 评估顺序、阶段、首次命中：以 §1.3 树 + `getOrderedReportRules` 为准。资格优先级
   `R0 > R1 > R9 > R4 > R2 > R3 > R8 > R5 > R6 > R7`。
2. 谓词、公式、比较方向、边界：以 §5 对应 Java 为准，不得用 §1.3 缩写替代公式。
3. R5/R6 的“非框架”前置以 §1.3 标题和类名为准，即使 Java `match()` 漏了 `isFramework()`。
4. 金额容差：方案 Java 写了 `+0.1` 的地方必须保留。
5. 本次比较字面值以优化方案 Java 为准（`0/1`）。工作簿 `4/5` 只能记 warning 级
   `SOURCE_CODING_DIVERGENCE`，不得进入 active when。
6. 视图、wiki、私有视图原文、工作簿公式都不是本次规则权威。

## 授权边界

本裁决授权：离线构造新规则块、新确认目录、新 `RuleStructureCandidateV3`、
`RuleParseResultV3`、整批 `FactBindingRequest 3.0.0` 与 Agent 2 readiness。

以下仍需单独授权，本次未执行：

- 任何 MongoDB 写入（含 insert-only）；
- DeepSeek 调用、SQL Server 访问、SqlBot 修改或 `generate-v3`；
- 原始数据释放规则导入；
- 正式发布或 `executable=true`。

## 产物身份

权威位置见 [PROG-20260920](PROG-20260920.md) 与
[generated-rules/report-release-v3-formula-20260920/](../generated-rules/report-release-v3-formula-20260920/README.md)。
公开仓库不写入优化方案正文、内部表列、SQL 或 `.env`。
