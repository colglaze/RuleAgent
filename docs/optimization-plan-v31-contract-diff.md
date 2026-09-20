# 优化方案 3.1.0：新旧契约差异与 SqlBot 接入要求

- 日期：2026-09-17
- 对应需求：[REQ-20260917-01](REQ-20260917-01-optimization-plan-rule-handoff.md)
- SqlBot 接口（本仓库交出、不修改 SqlBot）：[DEV-20260917-02](DEV-20260917-02-sqlbot-complete-delivery-intake.md)

## 冻结的 3.0.0 与新增的 3.1.0

| 工件 | 3.0.0（2026-09-05 交付） | 3.1.0（本次） |
| --- | --- | --- |
| Catalog | 无 derivation；digest `82dbd05a…` 绑定旧确认目录 | 仍无 derivation；新 catalogId/version/digest |
| Candidate | 五阶段 minLength=1；无运行参数；普通 `all` | 运行参数、`allMembers`、空阶段 + `emptyStageReason` |
| RuleParseResult | `sourceSha256` 关闭到 1402 字符规则块；只有 candidateRef/catalogRef | `sourceSha256`=文件字节；另存 parseInputSha256、提取章节、extractorVersion；`deliveryRef` 指向完整载荷哈希 |
| FactBindingRequest | 标量 result；无 parseInputSha256 | `cardinality=scalar\|set`；双重来源哈希 |
| 持久化 | Schema v5，result + batch | Schema v6 在既有 V3 集合增加 catalog/candidate payload、purpose、双重哈希 |
| 用途 | 未机器门禁 | 旧版本只允许 `historical-audit`；新版本用于 `optimization-plan-generation` |

3.0.0 不得塞入运行参数或集合量词。3.1.0 不得静默降级为 3.0.0。

2026-09-20 完全一致对齐后，**唯一待消费**的 3.1.0 身份为
`REPORT_RELEASE_ALL_001@20260920T131600000000Z-c049af189fc3-6d94836af30f` 与
`RAW_DATA_RELEASE_ALL_001@20260920T131600000000Z-c049af189fc3-2845743f259a`
（[BIZ-20260920-03](BIZ-20260920-03-optimization-plan-full-alignment.md)）。
2026-09-17 的 3.1.0 与 2026-09-20 的 3.0.0 公式树都不是本用途交付。

## Agent1 已落实的门禁

- 读取完整交付时校验 tree/catalog/result/batch 闭包；缺任一则 `consumable=false`。
- 旧 ruleVersion `REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a` 不能用于 optimization-plan-generation 或 sql-compilation。
- 新 persist 入口绑定优化方案文件哈希；旧 `persist_report_release_v3_delivery.py` 信任锚不变。

## SqlBot 仍须独立实现

详见 [DEV-20260917-02](DEV-20260917-02-sqlbot-complete-delivery-intake.md)。当前 SqlBot 生产代码未改。新 handoff 完成 **不等于** 总 SQL 已生成。
