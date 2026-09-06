# REQ-20260902-01：Rule Schema 3.0 与 Agent 2 就绪交接

- 状态：`IMPLEMENTED_SLICE_1_2`
- 日期：2026-09-02
- 恢复说明：原文件未包含在提交 `65a9684`；2026-09-05 根据同一提交中的 PRD、技术设计、
  实施与进度记录重建，并由用户本次“补齐所需文件”的要求确认恢复范围。
- 业务决策：[BIZ-20260902-01](BIZ-20260902-01-rule-v3-agent2-ready-boundary.md)
- 技术设计：[DEV-20260902-01](DEV-20260902-01-rule-contract-v3-agent2-ready-handoff.md)

## 问题与目标

Schema 2.0 能保存条件 AST，但无法直接表达项目报告规则中的状态守卫、有序放行路径、后置门禁、
排除条件和多结果降级。V3 首两个切片建立独立的确认事实目录和规则结构候选，使模型只能引用经过
业务确认的逻辑事实；缺失事实必须显式阻断。

## Slice 1/2 范围

- `BusinessConfirmedFactCatalogV3`：冻结事实编码、类型、粒度、参数角色、值域、空值契约、证据、
  binding profile 引用和 canonical digest。
- `RuleStructureCandidateV3`：固定五阶段 `stateGuards -> prerequisites -> eligibility -> postGates ->
  exclusions`，支持有序优先级、多 outcome、默认结果、阻断和候选事实。
- Pydantic、Draft 2020-12 Schema、确定性语义校验和多结果解释器。
- 规则块只从调用方显式提供的文本中按唯一规则 ID 提取；不扫描目录。
- REPORT_RELEASE 恢复 profile 必须精确提取用户确认的有序规则块，校验私有 bundle、工作簿和规则块
  三重哈希；详细 SQL 规则只作核对证据。
- DeepSeek 只通过显式 V3 入口调用；一次运行共享 1–3 次硬预算，默认 1 次。Schema/语义错误可在
  内存中纠错，业务确认缺口立即停止。

## 非目标

不生成测试案例、`RuleParseResultV3`、`FactTemplateRequestV3`、SQL、物理映射、规则版本、发布或执行
状态；不接入 V2 默认入口，不持久化，不连接 MongoDB/SqlBot/SQL Server。私有 XLSX、视图 SQL、
完整业务规则和 binding profile 不进入公开仓库。

## 验收标准

- 两个静态 Schema 与 Pydantic 权威模型确定性一致，合法/非法合成样例可离线复核。
- 目录 digest、证据闭包、binding 状态、枚举值域和重复编码安全失败。
- 候选目录身份、五阶段顺序、全局 ruleCode/condition id、阶段内 priority、事实引用闭包和类型通过
  确定性门禁。
- blocked 规则没有 `when/outcome/reasonCode`；active 规则不引用目录外事实。
- 任一候选级阻断使解释结果为 `INDETERMINATE`；缺失输入不当作 null。
- 后置门禁或排除可将前序 `READY` 降级；纠错预算不超过 3，业务缺口不消耗剩余次数。
- 已填写 XLSX 单元格按用户确认进入 source-bound catalog；工作表核对状态不参与可信度推断。任何
  与有序规则的冲突必须保留为 blocking，不能自动改写。
- 默认测试离线，V1/V2 行为保持兼容。
