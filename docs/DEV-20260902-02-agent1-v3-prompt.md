# DEV-20260902-02：Agent 1 V3 ruleStructure Prompt

- 状态：`IMPLEMENTED_RECONSTRUCTED`
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
