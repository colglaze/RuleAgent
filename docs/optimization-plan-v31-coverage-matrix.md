# 优化方案 3.1.0：来源节点 → 规则条件 → 事实请求 → 测试案例

- 日期：2026-09-20
- 对应需求：[REQ-20260917-01](REQ-20260917-01-optimization-plan-rule-handoff.md)
- 裁决：[BIZ-20260920-03](BIZ-20260920-03-optimization-plan-full-alignment.md)
- 机器来源：`rule_reader.domain.optimization_plan.coverage.COVERAGE_ROWS`
- 案例预期由人工按 §1.3 / §5.1 / §5.2 独立编写，求值器只核验，不生成预期。
- 本表是「完全一致」门禁；任一行正反案例对不上则任务失败。

| 来源节点 | 规则条件 id | 事实 / 运行参数 | 命中案例 | 不命中案例 |
| --- | --- | --- | --- | --- |
| §1.3 报告标志 3×3 + 未知 | `NO_PROJECT_REPORT` / `REPORT_AVAILABILITY_PENDING` | `task.project_report_flag`, `task.qc_report_flag` | `report-flags-1-1`, `report-flags-missing-both`, `report-flags-0-missing` | `report-flags-0-1`, `report-flags-0-0` |
| §1.3 / §5.2 线下/批量码 0 | `OFFLINE_REPORT_RELEASED` / `r9-batch` | `task.offline_report_release_flag`, `task.batch_report_release_flag` | `report-offline-0`, `r9-batch-0` | `report-offline-4-not-already`, `r9-batch-5-not-hit` |
| §5.2 R0 零金额，NULL 继续 | `r0-zero` | `order.amount` | `r0-zero` | `r0-null-continues` |
| §5.2 R1 类型 + 已完成节点，不去重 | `r1-count` | `release.special_application_count` | `r1-count-positive`, `r1-duplicate-nodes` | `r1-no-match`, `r1-unknown` |
| §5.2 R4 有无原始数据码=0 且完工日含截止日 | `r4-present` / `r4-date` | `task.raw_data_present_flag`, `task.completion_date`, 参数 `rawDataReleasedCutoffDate` | `r4-on-cutoff`, `r4-after-cutoff` | `r4-before-cutoff`, `r4-presence-1-on-cutoff`, `r4-null-flag`, `r4-null-date` |
| §5.2 R2 来源 2 | `r2-overseas` | `order.source_code` | `r2-overseas` | `r2-not-overseas` |
| §5.2 R3 70%/50% 分档 | `r3-special-and-tier` | `task.product_id`, `task.task_amount`, 金额构成, `order.arrival_amount_including_deposit` | `r3-low-endpoint`, `r3-high-endpoint` | `r3-low-insufficient`, `r3-high-insufficient`, `r3-null-arrival`, `r3-insufficient-enterprise-not-r5` |
| §5.2 R8 当天相等、酵母、上线日 | `r8-effective` / `r8a-day` / `r8-yeast` | 完工日、`task.task_amount`、开票、`task.product_type_code`、`task.no_main_service_flag` | `r8a-day-n`, `r8b-day-n`, `r8c-day-n`, `r8-yeast`, `r8-yeast-on-go-live` | `r8a-day-n-minus-1`, `r8a-day-n-plus-1`, `r8-before-go-live`, `r8-yeast-before-go-live` |
| §5.2 R5 非框架企业 100% | `r5-all` / `r5-pay` | 企业/框架标志、到款、完工金额 | `r5-full-arrival`, `r5-boundary` | `r5-insufficient`, `r5-framework-skips-to-r7`, `r3-insufficient-enterprise-not-r5` |
| §5.2 R6 A/B 与合同五支 | `r6-a` / `r6-b` / `seal-five` | 到款、押金、`order.seal_scope_contract_ids`, `contract.*` | `r6-condition-a`, `r6-condition-b`, `r6-contract-*` | `r6-empty-contracts`, `r6-contract-unsealed`, `r6-contract-contact-esign-blocked`, `r6-framework-skips-to-r7` |
| §5.2 R7 框架 80% 或押金 20% | `r7-pay` / `r7-deposit` | `order.framework_type`, 到款、押金 | `r7-arrival-80`, `r7-deposit-20`, `r5-framework-skips-to-r7` | `r7-insufficient` |
| §1.3 合并组全员满足 | `merge-all-members` | `report.merge_group_present`, `report.merge_group_member_ids` | `merge-partial` | `merge-empty`, `merge-duplicate-and-released`, `merge-unknown-member` |
| §1.3 仅项目报告 OA | `oa-in-process` | `task.in_project_report_release_oa` | `oa-blocks-ready` | `r0-zero` |
| eligibility 首个命中后仍过后置 | `R0` then OA/merge | `order.amount` 加后置事实 | `first-hit-r0-over-r1` | `oa-blocks-ready`, `merge-partial` |
| §1.3 D 前提与 D0–D4 | `DATA_*` / `d0`–`d4` | 原始数据目录事实 | `data-*` 命中与 `d0`–`d4` 命中 | `data-offline-0-not-already`, `data-presence-null`, `d0-null-continues`, `d1-no-match`, `d2-not-overseas`, `d3-not-closed`, `d4-insufficient` |
| §5.2 D4 单细胞附加支 | `d4-single-cell` / `d4-experiment-complete` | `task.product_type_code`, `order.closed_flag`, `order.sequencing_services_complete` | `d4-single-cell-closed`, `d4-single-cell-sequencing`, `d4-single-cell-terminated` | `d4-single-cell-blocked`, `d4-null-arrival` |

离线求值只证明草稿树在合成事实上可判定，不等于生产执行或 SqlBot 已生成总 SQL。R4 不再使用数据释放状态「已释放」。
