# BUG-20260906-05：真实 DeepSeek Agent 1 无法在《项目报告释放规则》上收敛出合法 V2 候选

- 来源 REQ：[REQ-20260818-03](REQ-20260818-03-rule-parser.md)、[REQ-20260827-02](REQ-20260827-02-deepseek-retry-audit-idempotency.md)
- 关联记录：[PROG-20260906](PROG-20260906.md)、历史同类缺陷 [BUG-20260902-01](BUG-20260902-01-latest-rule-agent1-semantic-rejection.md)、[BUG-20260903-02](BUG-20260903-02-agent1-v3-single-call-schema-rejection.md)
- 状态：`OPEN - 21 次真实调用未收敛；等待用户决策（继续有界重试 / 两阶段流程改造 / 维持 reviewed_import 路线）`

## 现象

2026-09-06 用户要求"调用 Agent 1 生成一版 JSON 规则并写入 MongoDB"。以权威来源《项目报告释放规则》
（bundle 路径 `sources/project-release-rules/规则agent规划/报告和数据的释放规则/项目报告释放规则.md`，
规范化后 7,501 字符，SHA-256 `562eabd40e5a5701fb9515499b542a6e2ff46056464621b1abb0a7c37f116e4d`）
执行 `rule-reader parse --file 项目报告释放规则.md --persist`，共 5 次运行、21 次真实
`deepseek-v4-flash` 调用，全部被门禁拒绝，未产生任何可持久化草稿，MongoDB 未写入任何规则。

## 失败面演化（门禁逐级前移）

| 运行 | Prompt / 配置 | 尝试 | 最终结果 | 关键失败点 |
| --- | --- | --- | --- | --- |
| 1 | v6，maxTokens=16384 | 3 | `CANDIDATE_JSON_INVALID` | 每次输出恰为 16384 tokens，JSON 被输出上限截断 |
| 2 | v6，maxTokens=65536 | 3 | `CANDIDATE_SCHEMA_INVALID` | JSON 完整后，`rootCondition.children[2].children[0].right.value` 写入非法（疑似 null 字面量） |
| 3 | v7（新增 10b 判空规则） | 3 | `CANDIDATE_SEMANTIC_INVALID` | 通过 Schema；4 个事实未被闭包引用、day_60/75/180 三个日期比较类型不兼容、7 个案例求值不符 |
| 4 | v8（新增 10c/10d/10e） | 6 | `CANDIDATE_SEMANTIC_INVALID` | 闭包与类型问题消失；仅剩 6 个案例 `indeterminate`；第 2-6 次输出逐字节相同（completionTokens 均为 22,808） |
| 5 | v8 + 校验器增强 | 6 | `CANDIDATE_SEMANTIC_INVALID` | 错误已能列出每个案例缺失的具体事实；第 2-6 次输出仍逐字节相同（completionTokens 均为 24,308） |

总 token 消耗约 1,076,582（明细见 5 份脱敏 stderr 日志，存于 git 忽略的
`artifacts/v2-agent1-real-runs-20260906/`，SHA-256：run1 `d1e255c7…`、run2 `d3025daa…`、
run3 `b0435d78…`、run4 `9a58d6e1…`、run5 `38f24d03…`）。

## 复现

```bash
RULEREADER_DOCUMENT_ROOT=<bundle 的 报告和数据的释放规则 目录> \
RULEREADER_MONGODB_URI=<认证 URI> \
RULEREADER_DEEPSEEK_API_KEY=<key> \
RULEREADER_DEEPSEEK_BASE_URL=https://api.deepseek.com \
RULEREADER_DEEPSEEK_MODEL=deepseek-v4-flash \
RULEREADER_DEEPSEEK_MAX_OUTPUT_TOKENS=65536 \
RULEREADER_DEEPSEEK_MAX_RETRIES=5 \
.venv/Scripts/rule-reader.exe parse --file 项目报告释放规则.md --persist
```

每次运行均输出脱敏 JSON 错误与完整 attempt 审计（request ID、Provider completion ID、逐次
outcome、token usage），与 `artifacts/` 中日志一致。

## 根因分析

> 2026-09-07 纠偏：本节第 2、3 条是基于当日会话内观察的**分析推断**，不是可复现结论。重试
> 反馈是否按预期传递给模型、进程内幂等缓存是否介入重放、DeepSeek 适配器是否改变请求/响应，
> 均未被系统性排除；当时只是没有观察到这些环节的异常。

1. 运行 1 是纯配置问题（输出上限低于该文档真实输出规模 ~22k tokens），已通过环境变量解决。
2. 运行 2-3 反映 Prompt 未覆盖契约的三个高阶约束（判空一元操作符、引用闭包、日期比较范式），
   已通过 `rule-parser-v7`/`v8` 补充并配回归测试；第 4、5 次运行证明这些修正有效（失败面推进
   到最后的测试案例一致性）。
3. 运行 4-5 暴露当前最主要的疑似阻断：模型在 `retryFeedback` 明确给出"每个案例缺失哪些 given
   值"的前提下，连续多次返回与前一候选逐字节相同的输出，不修改 `testCases`。推断为模型在长
   候选（~24k tokens 输出）+ 大反馈文本下的行为局限，不是校验器信息不足；如后续继续真实调用，
   应在可留存日志的条件下先复核反馈传递、幂等缓存与适配器三个环节，再确认该推断。

## 影响与边界

- 正式库没有被写入任何新规则；本缺陷不产生可交付草稿。
- 门禁行为全部正确（fail-closed），校验器增强本身是有价值的回归资产。
- 与 2026-09-02 的历史失败（[BUG-20260902-01](BUG-20260902-01-latest-rule-agent1-semantic-rejection.md)）
  相比，本次通过 Prompt 修订推进到了更深的校验层，但同样未能产出有效候选。

## 修复验收（满足其一即关闭）

1. 在不降低任何门禁的前提下，同一来源的一次真实运行产出通过全部校验的候选并成功 `--persist`
   （需用户授权调用次数）。
2. 经新 REQ/DEV 决策把 V2 解析改为"结构/案例两阶段"调用（参考 [DEV-20260902-02](DEV-20260902-02-agent1-v3-prompt.md)
   的 V3 ruleStructure 单阶段模板），使反馈作用于更小的输出面，并在真实运行中验证收敛。该方案
   目前只有设计意图：结构/案例两阶段尚未实现，也未经过任何真实 Provider 验证，不能预先保证
   收敛或消除输出截断。
3. 用户明确决定该文档继续沿用 reviewed_import 路线（Phase 1.9/confirmed V3 先例），本缺陷转为
   "不再以真实 Agent 1 生成该规则"的关闭说明。

### 路径②立项要求（若选择两阶段改造）

立项后先冻结 REQ/DEV 再编码，至少明确：两阶段契约与 Schema、阶段间数据传递、总调用预算上限、
阶段门禁（结构阶段通过全部校验后才允许进入案例阶段）、失败退出条件（预算耗尽或连续无改进即停，
不自动追加调用）与离线验收样例；真实 Provider 验证与 MongoDB 写入分别保留用户独立授权。

## 证据状态（2026-09-07 纠偏）

- 当日运行输出与 5 份脱敏 stderr 日志随会话即时生成，未留存到当前机器可审计的位置（本仓库
  git 忽略的 `artifacts/v2-agent1-real-runs-20260906/` 目录在当前工作区不存在），原始审计日志
  构成证据缺口；失败面演化表与 token 消耗只能作为当日会话记录引用，无法在当前环境复核。
- 默认离线测试基线 `203 passed, 6 deselected` 已于 2026-09-07 在本机复现（`.venv/Scripts/python.exe
  -m pytest -q`），这是当前可直接复现的证据。
