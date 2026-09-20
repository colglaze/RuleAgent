# DEV-20260920-03：Agent1 优化方案 3.1.0 离线生成

- 状态：`implemented`
- 日期：2026-09-20
- 对应需求：[REQ-20260920-01](REQ-20260920-01-agent1-optimization-plan-generation.md)
- 复用：[DEV-20260917-01](DEV-20260917-01-optimization-plan-rule-handoff.md)、
  [DEV-20260920-02](DEV-20260920-02-optimization-plan-full-alignment.md)
- 不替代：Schema 2.0 `RuleParsingService`、Schema 3.0 `RuleStructureParsingServiceV3`

## 1. 生成器

Agent1 的 3.1.0 路径 **不调用模型**。节点只调用领域转译器
`build_report_delivery` / `build_data_delivery`。parser 元数据保持：

- `provider=reviewed_import`
- `model=optimization-plan-translator-v1`
- `promptVersion=optimization-plan-v31-align-20260920`
- `parserVersion=0.13.0`

真实 DeepSeek 3.1.0 生成不在本切片；关闭路径仍见
[BUG-20260906-05](BUG-20260906-05-agent1-v2-real-call-convergence-blocker.md)。

## 2. LangGraph

服务：`OptimizationPlanParsingService`（`application/rule_parsing/workflow_v31.py`）。

State（显式 TypedDict；不含 Client、文件句柄、密钥、解析输入正文）：

| 字段 | 说明 |
| --- | --- |
| 来源身份六字段 | `SourceIdentityV31` |
| `report_delivery` / `data_delivery` | 领域交付对象 |
| `error` | `ParseIssue` 或空 |

| 节点 | 职责 | 失败码 |
| --- | --- | --- |
| `check_identity` | 校验提取器版本、章节、文件哈希 ≠ 解析输入哈希 | `CANDIDATE_SEMANTIC_INVALID` |
| `generate_report` | 调用报告转译器 | 语义/Schema 码 |
| `generate_data` | 调用原始数据转译器 | 语义/Schema 码 |
| `gate_delivery` | draft、不可执行、purpose、两套隔离、禁止历史 3.0.0 身份 | `CANDIDATE_SEMANTIC_INVALID` |

边：`START → check_identity → generate_report → generate_data → gate_delivery → END`。
任一节点写入 `error` 后条件边直达 `END`，不继续生成。无重试、无模型预算。

审计：单次 `SUCCESS` 或失败码；`max_attempts=1`；无 token usage；无 provider request id。

## 3. 适配器

- 读取：`infrastructure/optimization_plan_source.py`。只允许
  `--source-root` + 冻结相对路径
  `sources/project-release-rules/项目报告和原始数据释放优化方案.md`。
  拒绝穿越、非文件、非 `.md`、非 UTF-8。不把正文写入日志。
- 写出：`infrastructure/optimization_plan_artifacts.py`。写
  `report/`、`data/` 下 catalog/candidate/result/requests/manifest 与顶层 summary。
- CLI：`rule-reader parse-optimization-plan --source-root <root> --output-dir <dir>`。
  无 `--allow-provider`。`--persist` 为可选 insert-only 落库，默认关闭。
- `scripts/build_optimization_plan_v31_delivery.py` 调用同一服务与写出器，不 persist。
- `scripts/persist_optimization_plan_v31_delivery.py` 与 CLI `--persist` 共用
  `application/v31_persistence/packages.py`。

## 4. 非目标实现

不改 HTTP parse。不在本图调用 `DeepSeekChatModel`。LangGraph 节点不初始化 MongoDB。
MongoDB 只在 CLI `--persist` 或独立 persist 脚本中出现。

## 5. 测试

默认测试用合成 identity 与临时目录。覆盖：与领域 builder 哈希一致、非法身份失败、
错误文件哈希失败、CLI 子命令存在、`--persist` 默认关闭、缺失源文件失败、`workflow_v31`
源码不含 deepseek、磁盘包装经同一 loader 的 FakeDatabase insert-only 落库。
