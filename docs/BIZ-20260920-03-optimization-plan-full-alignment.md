# BIZ-20260920-03：优化方案完全一致硬门禁（报告 + 原始数据）

- 状态：`APPROVED_AND_PERSISTED`
- 日期：2026-09-20
- 对应需求：[REQ-20260917-01](REQ-20260917-01-optimization-plan-rule-handoff.md)
- 权威决策（仍有效）：[BIZ-20260917-01](BIZ-20260917-01-optimization-plan-authority-agent1.md)
- 实施：[DEV-20260920-02](DEV-20260920-02-optimization-plan-full-alignment.md)
- 收回：
  - [BIZ-20260920-01](BIZ-20260920-01-report-release-formula-v3.md)「暂时不导入原始数据释放规则（D0–D4）」；
  - [BIZ-20260917-01](BIZ-20260917-01-optimization-plan-authority-agent1.md) 第 5 条把 R4 拆成「数据释放状态=已释放 + 完工日」。
- 不替代已落库版本：`REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a`
- 不得当作本任务交付：2026-09-17 的 3.1.0 原树、2026-09-20 的 3.0.0 公式树（含建模 A 盖章计数与 `merge_group_eligible` 黑盒）

## 硬门禁

Agent1 产出必须与私库优化方案判定完全一致，否则不得落库、不得交给 Agent2、不得声称可生成视图式 SQL。

判定权威 = §1.3 结构 **加上** §5.2 可执行示例。§1.3 粗于 §5.2 时以 §5.2 为准。冲突解释顺序仍见
[BIZ-20260920-01](BIZ-20260920-01-report-release-formula-v3.md)：顺序/首个命中跟 §1.3 与
`getOrderedReportRules`；谓词/公式/边界跟 §5 Java；R5/R6 非框架跟 §1.3 标题；金额 `+0.1` 跟
Java；比较码跟 Java `0/1`。

视图、wiki、工作簿公式都不是权威。Java 是需转译并核验的来源，不是已实现规则。

本次「完全一致」覆盖**项目报告和原始数据**两套规则。

## 本切片必须并入

1. Schema **3.1.0** 契约：`runtimeParameters`、`allMembers`、空阶段、双重来源身份、完整
   tree/catalog/result/batch。
2. 任务单金额 `task.task_amount` 且 `grain=task`；产品属性在任务粒度（`task.product_id`、
   `task.product_type_code`、`task.no_main_service_flag`）；R3/R5/R6/R7/D4 金额树在 `when` 内展开。
3. 合并组展开为可查询成员集合 + `allMembers`（已释放三态或精简前提+资格命中；空组通过；缺成员不得判全员满足）。禁止 `merge_group_eligible` 黑盒。
4. R6 盖章五支进入条件树（成员合同谓词）。空合同范围失败。禁止只写在 queryRequirements 描述里。
5. R1/D1 的 queryRequirements 必须含申请类型与已完成审批节点，计数不去重。
6. 独立原始数据 ruleSet：数据侧前提 + D0–D4（含单细胞附加支）。
7. 覆盖矩阵每个来源节点至少有命中/不命中（含 NULL、边界、N-1/N/N+1、合并组部分不满足、R3 标志真但到款不足）。案例预期人工按方案编写，求值器只核验。

## 本切片收回并改写的判定

| 项 | 旧决定 | 本切片 |
| --- | --- | --- |
| R4 | 数据释放状态=`已释放` 且完工日 ≥ 截止日 | §5.2 Java：有无原始数据码 = `0`，且完工日 ≥ `2024-11-21`。不得再用「已释放」拆分 |
| D0–D4 | 2026-09-20 公式树任务暂时排除 | 必须导入独立原始数据 ruleSet |
| 盖章 | 2026-09-20 建模 A：订单级 count，五支只在描述中 | 五支进入 `allMembers.memberPredicate` |
| 合并组 | 2026-09-20 `report.merge_group_eligible` | 展开为成员集合量词 |
| 契约 | 2026-09-20 公式树为 3.0.0 | 唯一待消费交付为 3.1.0 |

方案正文写了、Java `match()` 漏写的两项必须保留：R5/R6 非框架前置；R8 上线日 `2026-04-15`（整个 R8 的运行参数前置，含酵母支）。

## 身份与写入边界

新 `ruleVersion` / `catalogDigest`，insert-only。禁止覆盖已落库 confirmed 版本。2026-09-20 用户已授权并将对齐身份写入本机 `rule_reader`（见 [PROG-20260920](PROG-20260920.md)）。**仍不得 SqlBot intake**，除非另行现场授权。完成不等于总 SQL 已生成。

公开仓库、测试夹具、日志不得写入私有原文、内部表列、SQL 或凭据。默认测试用合成数据。
