# BIZ-20260818-02：使用 Python 与 LangGraph

- 状态：`ACCEPTED`
- 日期：2026-08-18
- 来源 REQ：[REQ-20260818-01](REQ-20260818-01-vibe-coding-bootstrap.md)
- 影响范围：项目级开发语言、Agent 编排框架和长期方案技术栈

## 1. 决策

1. RuleReader 的应用代码和测试代码统一使用 Python。
2. Rule Parsing Agent 及后续 Agent 工作流统一使用 LangGraph 编排。
3. 不再采用长期方案原建议的 Java、Spring Boot 和 Spring AI。
4. LangGraph 位于应用编排层；规则领域模型、Schema 校验和确定性语义校验保持框架无关。
5. 本决策当时未指定 Python 版本和模型 Provider；后续 [BIZ-20260818-03](BIZ-20260818-03-python311-deepseek.md) 已将其分别锁定为 Python `3.11.9` 和 DeepSeek。包管理器、Web/API 框架及数据库访问库仍由对应 DEV 决定。

## 2. 原因

- 用户明确选择 Python 作为项目开发语言，并选择 LangGraph 作为 Agent 编排框架。
- LangGraph 适合把读取文档、模型解析、结构校验、语义校验和失败处理表达为显式状态流。
- 将编排框架限制在应用层，可以让规则 Schema 和校验逻辑保持确定性、易测试且不被模型框架绑定。

## 3. 工程影响

- 后续工程骨架、工具链、类型检查、测试和打包方案必须围绕 Python 设计。
- LangGraph state 必须显式定义并可类型检查；node 保持单一职责，模型和文件副作用通过适配器隔离。
- 默认测试使用模型测试替身，并独立覆盖 node、edge、条件路由和失败 state。
- 根目录长期方案中的 Java 示例、`JAVA_PROVIDER`、Spring AI 和 Java 数据访问建议已同步改为 Python 技术表达。

## 4. 变更规则

若后续需要引入其他语言或替换 LangGraph，必须先创建新的 BIZ/DEV，说明迁移范围、兼容策略和测试证据；不得在单个功能任务中顺手更换技术栈。
