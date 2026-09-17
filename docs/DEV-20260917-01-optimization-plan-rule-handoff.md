# DEV-20260917-01：优化方案新交接实施设计

- 状态：`implemented-offline`
- 日期：2026-09-17
- 对应需求：[REQ-20260917-01](REQ-20260917-01-optimization-plan-rule-handoff.md)
- 业务决策：[BIZ-20260917-01](BIZ-20260917-01-optimization-plan-authority-agent1.md)

## 1. 契约版本

冻结的 3.0.0 契约不接受运行参数表达式、集合量词、双重来源身份、集合结果或完整交付引用。本需求新增 **Rule Schema / FBR / RuleParseResult 3.1.0**。Catalog 字段形状仍使用 3.0.0 模型（无 derivation），但 catalogVersion/digest 全新。

| 工件 | 版本 | 说明 |
| --- | --- | --- |
| `BusinessConfirmedFactCatalog` | 3.0.0 模型 + 新 digest | 不增加 derivation |
| `RuleStructureCandidate` | 3.1.0 | 运行参数、allMembers、空阶段、阶段语义 |
| `RuleParseResult` | 3.1.0 | 双重来源身份、runtime/members 案例、完整交付引用 |
| `FactBindingRequest` | 3.1.0 | `cardinality=scalar\|set`；ruleRef 含文件哈希与解析输入哈希 |
| 旧 3.0.0 交付 | 不变 | 用途门禁拒绝作为 optimization-plan-generation |

## 2. 来源身份

- `sourceSha256`：优化方案文件原始字节 SHA-256，不经换行规范化。
- `parseInputSha256`：提取器从 §1.3 + §5.1 + §5.2（至 §5.6 之前）切出的 UTF-8 文本哈希。
- `extractorVersion`：`optimization-plan-sections-v1`。
- `ruleVersion` 来源前缀（3.1.0）关闭到 **文件哈希** 前 12 位，不再关闭到提取块。
- 3.0.0 仍关闭到规则块哈希；旧解释不得改写。

## 3. 运行参数

候选声明 `runtimeParameters`。表达式新增 `kind=parameter`。截止日、求值日、上线日、会签截止日不是 FBR 数据库事实。求值时区固定 `Asia/Shanghai`；date/datetime 在比较“当天相等”前转为该时区的日历日。

绑定值：

- `rawDataReleasedCutoffDate` = `2024-11-21`（含当天）
- `timedReleaseEffectiveDate` = `2026-04-15`（含当天）
- `contractCountersignCutoffDate` = `2023-11-01`（含当天）
- `evaluationDate` 由调用方在求值时提供；离线案例显式给定

## 4. 集合量词

条件新增 `kind=allMembers`：

- `collectionFactCode` 指向 list 事实
- `emptyCollectionPolicy`：合并组 `pass`，合同范围 `fail`
- `duplicateMemberPolicy`：`uniquePreserveOrder`
- `missingMemberPolicy`：`indeterminate`
- `alreadySatisfied` / `memberPredicate` 在成员事实命名空间求值
- 成员谓词不得引用合并组自身结果

FBR 集合事实：`result.cardinality=set`，`dataType=list`。标量事实保持 `scalar`。

## 5. 空阶段

五阶段顺序不变。`postGates.rules` 允许为空，且必须声明 `emptyStageReason`（原始数据无合并组）。eligibility 不得为空。禁止编造永不命中的业务规则以满足旧 minLength=1。

## 6. 完整交付与持久化

沿用集合 `rule_versions_v3` 与 `fact_binding_handoff_batches_v3`，不写入 `rule_versions`。

MongoDB Schema **v6** 仅升级元数据并把完整交付字段写入既有 V3 集合：`catalog_payload`、`candidate_payload`、`parse_input_sha256`、`source_file_sha256`、`purpose`。不新增集合。

可消费完成条件：tree、catalog、result、batch 均可回读且哈希/版本/依赖闭包一致。规则已写入而 batch 失败时，重试必须幂等恢复；在闭包完整前 `consumable=false`。

新脚本 `scripts/persist_optimization_plan_v31_delivery.py` 绑定新 manifest 信任锚。旧脚本 `persist_report_release_v3_delivery.py` 及其 18 请求锚点保持不变。

## 7. 用途门禁

| ruleVersion | 允许用途 | 拒绝用途 |
| --- | --- | --- |
| `REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a` | `historical-audit` | `optimization-plan-generation`、`sql-compilation` |
| 本需求两个新版本 | `optimization-plan-generation` | 不得回退旧 18 条 |

Agent1 在导出/持久化/读取完成条件时执行该门禁。SqlBot 侧要求见 [DEV-20260917-02](DEV-20260917-02-sqlbot-complete-delivery-intake.md)。

## 8. 应用版本

应用包升级到 `0.13.0`。优化方案 profile 的 parserVersion 冻结为常量 `0.13.0`，不随后续包版本漂移。
