# DEV-20260917-02：SqlBot 完整交付接入要求（Agent1 交出，不修改 SqlBot）

- 状态：`interface-specified-not-implemented-in-sqlbot`
- 日期：2026-09-17
- 对应需求：[REQ-20260917-01](REQ-20260917-01-optimization-plan-rule-handoff.md)
- 范围：只规定 SqlBot 后续必须实现的消费契约与验收。**本任务不修改 SqlBot 生产代码。**

## 1. 新交接到来不是总 SQL 已就绪的证明

Agent1 交付可求值规则树与可查询事实。SqlBot 仍须独立升级：

1. 读取完整交付（tree + catalog + result + batch），而不是只读 18 条 usages。
2. 解析 FBR **3.1.0**（含 `cardinality=set`、双重来源哈希、运行参数声明）。
3. 按规则树组合事实查询；禁止把描述里的公式写成 SQL。
4. 以 Agent1 离线求值案例为差分基准。

缺少完整闭包或用途不匹配时必须阻断，不得回退 2026-09-05 batch `0df35b35…`。

## 2. 必须实现的消费门禁

```text
selectDelivery(purpose, ruleSetId) -> CompleteDelivery
preconditions:
  purpose in supportedPurposes
  delivery.schemaVersion == "3.1.0" for optimization-plan-generation
  delivery.purpose allows the requested purpose
  catalog, candidate, result, batch all present
  hashes close (sourceFile, parseInput, catalogDigest, candidate, result, batch)
  executable == false
  mapping remains unresolved until metadataReview
reject:
  2026-09-05 REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a
    for purpose optimization-plan-generation or sql-compilation
  any delivery missing catalog_payload or candidate_payload
  any V1/V2 document in collection rule_versions treated as this V3 delivery
```

## 3. 运行参数与集合结果

- `evaluationDate`、截止日、上线日是规则表达式参数，不是数据库列。
- 成员集合 FBR 返回实体键列表；SqlBot 必须能按成员键取成员事实，并在规则侧做全员量词，而不是生成“组成员 eligible 布尔列”。
- 普通 `all` 节点仍只是有限 AND。

## 4. metadataReview

旧两列测试批准不能继承为完整清单授权。必须按精确新 `ruleVersion` 重新批准物理映射。Agent1 只提供逻辑字段、实体关系、筛选、聚合和时间要求。

## 5. 验收（待 SqlBot 独立 REQ）

- 指定新报告版本时可以读取完整树，而不是 18 个坐标。
- 指定旧 2026-09-05 版本做 sql-compilation 时确定性失败。
- R3 分档、R8 当天相等、合并组部分不满足的离线案例与 Agent1 求值一致。
- 不声称“handoff 已写入”等于“总 SQL 已生成”。
