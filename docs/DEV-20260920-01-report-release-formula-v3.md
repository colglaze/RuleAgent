# DEV-20260920-01：项目报告释放公式树 V3 离线 profile

- 状态：`IMPLEMENTED_OFFLINE`
- 日期：2026-09-20
- 来源需求：[REQ-20260902-01](REQ-20260902-01-rule-contract-v3-agent2-ready-handoff.md)
- 业务裁决：[BIZ-20260920-01](BIZ-20260920-01-report-release-formula-v3.md)
- 复用契约：[DEV-20260906-01](DEV-20260906-01-rule-parse-result-v3.md)、
  [DEV-20260905-02](DEV-20260905-02-v3-agent2-handoff-readiness.md)

## 范围

一次纵向切片：新规则块 → 新 `BusinessConfirmedFactCatalogV3` → 有序五阶段
`RuleStructureCandidateV3`（资格规则全部 `active`，`when` 为 `all/any/not + compare` 树）
→ `RuleParseResultV3` + `FactBindingRequest 3.0.0` → Agent 2 readiness。

不实现：SqlBot、视图绑定、原始数据规则、MongoDB 写入、DeepSeek 调用。

## 禁止复用

不得把下列冻结脚本/标记当作本次交付：

- 旧 1402 字符规则块（SHA-256 前缀 `f285643e5b2b…`）；
- `scripts/report_release_v3_confirmed_profile.py`；
- `scripts/persist_report_release_v3_delivery.py` 冻结的旧 identity；
- 既有 18 事实黑盒目录与 16 个 `when=null` blocking 节点。

## 实现

- 规则块在公开仓库外的私有工作目录构造；第一行 `REPORT_RELEASE_ALL_001`；
  provenance 同时登记全文 SHA-256 与实际送入解析器的规则块 SHA-256。
- 新构建器：`scripts/report_release_v3_formula_profile.py`。
  `catalogId=REPORT_RELEASE_FORMULA_FACTS`，`catalogVersion=2026-09-20.2`，
  `parserVersion=0.12.0-formula-fix`。
- 表达式最小扩展：`kind=today`（无 FBR）；ISO 日期字面量推断为 `date`。
- 测试 given 可用保留键 `__evaluation_date` 覆盖评估日。
- R6 盖章建模 A：五分支只在两个订单级 count 的 queryRequirements/描述中。
- `report.merge_group_eligible` 仍是未展开 exists 黑盒。
- 金额比较的 `nullPolicy=indeterminate`，缺失金额不得静默变成资格失败。
- `mappingCandidate` 保持 `unresolved`；derived 不得进入 FactBindingRequest。
- 默认不写 MongoDB。若后续获 insert-only 授权，必须新文档、精确回读、历史条数只增不改。
  禁止覆盖已落库 confirmed 版本，也不得复用已作废的 `…T085100…` ruleVersion。

## 验证

默认套件中的 `tests/unit/test_report_release_v3_formula_profile.py` 覆盖身份、五阶段、
公式树非黑盒、解释器案例、readiness 与公开产物安全扫描。命令与结果见
[PROG-20260920](PROG-20260920.md)。
