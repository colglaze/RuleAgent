# DEV-20260920-02：优化方案 3.1.0 完全一致对齐（报告 + 原始数据）

- 状态：`implemented-persisted`
- 日期：2026-09-20
- 对应需求：[REQ-20260917-01](REQ-20260917-01-optimization-plan-rule-handoff.md)
- 业务裁决：[BIZ-20260920-03](BIZ-20260920-03-optimization-plan-full-alignment.md)
- 复用：[DEV-20260917-01](DEV-20260917-01-optimization-plan-rule-handoff.md) 的 Schema 3.1.0 与 Schema v6 路径

## 范围

一次纵向切片：在既有 3.1.0 领域模型上重做**唯一**待消费交付（报告 + 原始数据），使规则树与优化方案逐条一致。对齐切片本身不实现 DeepSeek、SQL、SqlBot。MongoDB 写入已于同日按用户授权完成（insert-only，证据见 [PROG-20260920](PROG-20260920.md)）。

不得把下列产物原样当作本任务交付：

- `REPORT_RELEASE_ALL_001@20260917T140000000000Z-c049af189fc3-74a69e146b34` 及其 R4「已释放」拆分；
- 2026-09-20 公式树 3.0.0（`generated-rules/report-release-v3-formula-20260920*`）。

## 建模冻结

- `catalogVersion=2026-09-20.3`，`promptVersion=optimization-plan-v31-align-20260920`，
  `parserVersion` 仍冻结 `0.13.0`。
- 固定 `generatedAt=2026-09-20T13:16:00+00:00`，ruleVersion 来源前缀仍关闭到优化方案**文件哈希**。
- R4：`task.raw_data_present_flag eq 0` 且完工日 `gte` 参数 `rawDataReleasedCutoffDate`
  （绑定 `2024-11-21`，含当天）。比较 `nullPolicy=fail`，与 Java「码为 0 且完工日非空且 ≥ 截止日」一致；NULL 不把整段资格打成 INDETERMINATE。
- 金额：`task.task_amount`（任务粒度）。累计完工金额在 `when` 内用 add/multiply 展开；到款比较保留 `+ 0.1`。
- 产品：`task.product_id`、`task.product_type_code`、`task.no_main_service_flag`，键 `taskId`。
- 框架/企业：仍用方案物理码集合 `{0,2}` / `{14,16}`，不用 09-20 的布尔黑盒。
- R6 盖章：`order.seal_scope_contract_ids` + `allMembers`（空集 `fail`）+ 五支 `memberPredicate`。
- 合并组：`report.merge_group_member_ids` + `allMembers`（空集 `pass`，缺成员 `indeterminate`）。
- 原始数据：独立 candidate / catalog / ruleVersion / FBR / 案例；`postGates` 空阶段。
- 公开产物：`generated-rules/optimization-plan-v31-20260920-align/`。默认测试只走合成 identity。

## 验证

`tests/unit/test_optimization_plan_v31.py` 与 `tests/unit/test_optimization_plan_v31_alignment.py`。
覆盖矩阵：[optimization-plan-v31-coverage-matrix.md](optimization-plan-v31-coverage-matrix.md)。
命令与结果见 [PROG-20260920](PROG-20260920.md)。

2026-09-20 用户授权后，`persist_optimization_plan_v31_delivery.py` 已将报告与原始数据两套身份
insert-only 写入本机 `rule_versions_v3` / `fact_binding_handoff_batches_v3`，Schema v6，精确回读通过。
