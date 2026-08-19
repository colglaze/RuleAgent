# BIZ-20260818-03：锁定 Python 3.11.9 与 DeepSeek

- 状态：`ACCEPTED`
- 日期：2026-08-18
- 来源 REQ：[REQ-20260818-01](REQ-20260818-01-vibe-coding-bootstrap.md)
- 前置决策：[BIZ-20260818-02：使用 Python 与 LangGraph](BIZ-20260818-02-python-langgraph.md)
- 影响范围：运行时版本、模型供应商、开发测试环境和模型适配器

## 1. 决策

1. RuleReader 的 Python 运行时版本锁定为 `3.11.9`。
2. 本地开发、自动化测试和 CI 使用相同的 Python `3.11.9`，避免版本漂移。
3. Rule Parsing Agent 的模型供应商选用 DeepSeek。
4. DeepSeek 必须通过独立模型适配器接入；领域模型、确定性校验和 LangGraph state 不依赖其 SDK 或原始响应类型。
5. 当前不指定具体 DeepSeek 模型 ID、SDK/HTTP 调用方式、Endpoint、采样参数和结构化输出策略，这些内容在 Phase 1 DEV 中冻结并验证。
6. 未经新的 BIZ/DEV，不接入其他模型供应商，也不配置静默 fallback。

## 2. 原因

- 用户明确指定 Python `3.11.9` 和 DeepSeek。
- 固定补丁版本可以让开发、测试和 CI 的行为保持一致。
- 供应商适配器隔离有利于测试超时、限流、空响应、非法 JSON 和 Schema 不匹配等失败路径。
- 暂不假定具体模型和调用库，避免在没有兼容性验证时写入错误或过时的 API 细节。

## 3. 工程影响

- 工程元数据、环境说明和 CI 必须校验 Python `3.11.9`。
- 依赖锁文件必须在 Python `3.11.9` 环境生成和验证。
- DeepSeek 凭据只允许从运行环境或本地未跟踪配置注入。
- 默认测试使用 DeepSeek 适配器的测试替身；真实调用测试必须显式启用并使用非敏感样例。
- 下一份 DEV 必须明确具体模型 ID、调用方式、超时、重试、限流、结构化输出与错误映射。

## 4. 变更规则

升级 Python、切换 DeepSeek 模型供应商或增加 fallback 都属于技术栈变更，必须先更新 BIZ/DEV，并提供兼容性和回归测试证据。
