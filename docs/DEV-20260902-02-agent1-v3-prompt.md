# DEV-20260902-02：Agent 1 V3 ruleStructure Prompt

- 状态：`IMPLEMENTED_RECONSTRUCTED（仅 ruleStructure 单阶段；两阶段为待设计方案，见下文验证状态边界）`
- 日期：2026-09-02
- 来源需求：[REQ-20260902-01](REQ-20260902-01-rule-contract-v3-agent2-ready-handoff.md)
- 当前版本：`rule-structure-v3.1`

## System Prompt 不变量

权威文本位于 `src/rule_reader/application/rule_parsing/prompt_v3.py`。Prompt 要求只返回一个符合
candidate Schema 的 JSON 对象；只生成 ruleStructure；禁止测试案例、版本、物理映射、SQL、凭据、
发布和执行状态；active 条件只能使用确认目录 factCode；缺失事实必须生成 proposed fact、blocking
issue 和 blocked rule；五阶段顺序、唯一 ID、priority、引用闭包和边界方向必须保持。

## User Payload

动态对象只包含：

- `task`
- `candidateSchema`
- `confirmedFactCatalog`
- `retryFeedback`
- `ruleText`
- 可选 `previousCandidate`

模型响应始终作为不可信输入重新经过 Pydantic 和确定性语义门禁。Prompt 不携带 API Key、连接串、
私有 bundle 或 SQL 原文；本文件不复制长 Prompt，避免双份权威文本漂移。

## 验证状态边界（2026-09-07 补记）

- 本文件冻结的只有 `ruleStructure` 单阶段 System Prompt 与 User Payload（`rule-structure-v3.1`），
  已批准用于离线场景；当前真实运行可用的生成分支也只有该 ruleStructure 单阶段分支。
- 进度/缺陷文档中提及的“`ruleStructure/testCases` 两阶段调用模板”是设计方向：testCases 阶段
  无冻结 Prompt、无实现、未经任何真实 Provider 验证；不得表述为“已验证的两阶段方案”，也不能
  据此断言两阶段解析可收敛或消除输出截断。confirmed V3 交付的成功来自 reviewed_import，
  与两阶段方案无关。
- [BUG-20260906-05](BUG-20260906-05-agent1-v2-real-call-convergence-blocker.md) 关闭路径②若立项，
  须以新 REQ/DEV 冻结两阶段契约、总调用预算、阶段门禁与离线验收标准后再实现；真实 Provider
  验证与 MongoDB 写入分别保留用户独立授权。
