# REQ-20260917-01：优化方案驱动的新版本规则与交接

- 状态：`IMPLEMENTED_PERSISTED_AWAITING_SQLBOT_INTAKE`
- 日期：2026-09-17
- 来源决策：SqlBot [BIZ-20260917-03](../../SqlBot/docs/decisions/BIZ-20260917-03-optimization-plan-authority.md)
- 可行性评估：SqlBot [DEV-20260917-02](../../SqlBot/docs/architecture/DEV-20260917-02-agent1-optimization-handoff-feasibility.md)
- 业务决策：[BIZ-20260917-01](BIZ-20260917-01-optimization-plan-authority-agent1.md)
- 技术方案：[DEV-20260917-01](DEV-20260917-01-optimization-plan-rule-handoff.md)
- 下游接口：[DEV-20260917-02](DEV-20260917-02-sqlbot-complete-delivery-intake.md)
- 前置：V3 Schema 3.0.0 与 Schema v5 持久化保持只读兼容；本需求不得覆盖 2026-09-05 交付

## 范围

以固定私有优化方案 §1.3 结构、§5.1 金额口径和 §5.2 可执行示例为权威，由 Agent1 离线发布：

1. 新事实目录及新 catalog digest（报告与原始数据各一份）。
2. 完整、可独立求值的规则树（两个独立 ruleSet）。
3. 新 `ruleVersion`（两个 ruleSet 不必共用版本号）。
4. 对应的新 `FactBindingRequest` 批次。
5. 内容闭包完整、可重复验证的交付包，以及沿用 `rule_versions_v3` /
   `fact_binding_handoff_batches_v3` 的完整载荷持久化路径。

2026-09-05 的旧 18 条交接不再作为本次优化方案生成输入。旧规则、旧批次、审计记录必须保留。

## 非目标

- 在 SqlBot 中补齐旧 18 条请求，或查询/复制现行释放视图以实现目标。
- 修改 SqlBot 生产代码、物理授权、SQL 生成或 AST 门禁。
- Agent1 自行授予物理表列、JOIN、grant、snapshot 或 context。
- 覆盖或删除旧 V3 版本、旧 batch 或恢复候选。
- 把规则标记为 `executable=true` 或已发布。
- 调用在线模型、连接生产数据库或执行来源 Java/SQL/工作簿公式（除非另有明确授权）。
- 把私有原文、内部表列、SQL 或业务数据写入公开仓库、测试夹具、日志或模型请求。

## 验收标准

1. 来源身份区分：`sourceSha256` = 优化方案原始文件字节哈希；另存解析输入/提取块哈希、提取章节、证据坐标和提取器版本。不得把旧 1402 字符块哈希解释为 catalogDigest 或文件哈希。
2. 报告规则顺序 R0→R1→R9→R4→R2→R3→R8→R5→R6→R7；命中即停仅限 eligibility 内部首个命中；初步 READY 后仍须经过合并组及 OA 后置约束。
3. 公式展开到条件树，复用 all/any/not/compare、算术和 dateAdd；不引入 catalog derivation，不把公式只写在 description。
4. 运行参数与数据库事实分离；截止日、求值日不得伪装成待查询字段。
5. 成员全员满足使用版本化集合量词，不得用普通 all 或 unresolved 布尔冒充。
6. 原始数据 D0–D4 为独立 ruleSet、独立树、独立版本、独立交接和独立案例。
7. 完整交付：同一 ruleVersion 的 tree/catalog/result/batch 均可按哈希回读；缺少任一依赖不可消费；部分写入不得报告为可用。
8. 新增受控交付入口；旧 persist 脚本与旧信任锚保持不变。
9. 旧批次“本用途不再可用”在 Agent1 有可执行用途门禁；SqlBot 消费门禁以接口文档交付，不修改其生产代码。
10. 默认测试使用合成数据，不依赖私有源文件、生产库或在线模型。

## 完成标准

- 相关自动化测试通过；覆盖矩阵、契约差异和验证命令已记录。
- 离线实现完成不等于真实落库或 SqlBot 已能生成总 SQL。2026-09-20 已按用户授权将对齐后的
  两个 3.1.0 `ruleVersion` insert-only 写入本机正式库；SqlBot intake 与总 SQL 仍未做。
