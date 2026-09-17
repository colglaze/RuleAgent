# 优化方案 3.1.0：来源节点 → 规则条件 → 事实请求 → 测试案例

- 日期：2026-09-17
- 对应需求：[REQ-20260917-01](REQ-20260917-01-optimization-plan-rule-handoff.md)
- 机器来源：`rule_reader.domain.optimization_plan.coverage.COVERAGE_ROWS`
- 案例预期由人工按 §1.3 / §5.1 / §5.2 独立编写，求值器只核验，不生成预期。

| 来源节点 | 规则条件 | 事实 / 运行参数 | 测试案例 |
| --- | --- | --- | --- |
| §1.3 报告标志 3×3 + 未知 | `NO_PROJECT_REPORT` / `REPORT_AVAILABILITY_PENDING` | `task.project_report_flag`, `task.qc_report_flag` | `report-flags-*`, `report-flags-missing-both`, `report-flags-0-missing` |
| §1.3 / §5.2 线下/批量码 0 | `OFFLINE_REPORT_RELEASED` / `R9` | `task.offline_report_release_flag`, `task.batch_report_release_flag` | `report-offline-0`, `report-offline-4-not-already`, `r9-batch-0`, `r9-batch-5-not-hit` |
| §5.2 R0 零金额，NULL 继续 | `R0` | `order.amount` | `r0-zero`, `r0-null-continues` |
| §5.2 R1 类型 + 已完成节点，不去重 | `R1` | `release.special_application_count` | `r1-count-positive`, `r1-duplicate-nodes`, `r1-no-match`, `r1-unknown` |
| §5.2 R4 已释放 + 含截止日 | `R4` | `data.release_status`, `task.completion_date`, 参数 `rawDataReleasedCutoffDate` | `r4-on-cutoff`, `r4-after-cutoff`, `r4-before-cutoff` |
| §5.2 R2 来源 2 | `R2` | `order.source_code` | `r2-overseas` |
| §5.2 R3 70%/50% 分档 | `R3` | `product.id`, 金额构成, `order.arrival_amount_including_deposit` | `r3-low-endpoint`, `r3-low-insufficient`, `r3-high-endpoint`, `r3-high-insufficient`, `r3-null-arrival` |
| §5.2 R8 当天相等与酵母例外 | `R8` | 完工日、金额、开票、品类、无主服务, 参数 `evaluationDate` | `r8a-day-n`, `r8a-day-n-minus-1`, `r8a-day-n-plus-1`, `r8a-datetime-shanghai`, `r8b-day-n`, `r8c-day-n`, `r8-yeast`, `r8-before-go-live` |
| §5.2 R5 企业 100% | `R5` | 企业/框架标志、到款、完工金额 | `r5-full-arrival`, `r5-boundary`, `r5-insufficient` |
| §5.2 R6 A/B 与合同五支 | `R6` | 到款、押金、`order.seal_scope_contract_ids`, `contract.*` | `r6-condition-a`, `r6-condition-b`, `r6-empty-contracts`, `r6-contract-*` |
| §5.2 R7 框架 80% 或押金 20% | `R7` | `order.framework_type`, 到款、押金 | `r7-arrival-80`, `r7-deposit-20` |
| §1.3 合并组全员满足 | `MERGE_GROUP_UNSATISFIED` | `report.merge_group_present`, `report.merge_group_member_ids`, 成员快照 | `merge-partial`, `merge-unknown-member`, `merge-empty`, `merge-duplicate-and-released` |
| §1.3 仅项目报告 OA | `OA_PROCESS_SCOPE` | `task.in_project_report_release_oa` | `oa-blocks-ready` |
| eligibility 首个命中后仍过后置 | `R0` then OA/merge | `order.amount` 加后置事实 | `first-hit-r0-over-r1`, `oa-blocks-ready`, `merge-partial` |
| §1.3 D 前提与 D0–D4 | `DATA_*` / `D0`–`D4` | 原始数据目录事实 | `data-*`, `d0-*`, `d1-count`, `d2-overseas`, `d3-closed-loop`, `d4-*` |
| §5.2 D4 单细胞附加支 | `D4` | `product.category_code`, `order.closed_flag`, `order.sequencing_services_complete` | `d4-single-cell-blocked`, `d4-single-cell-closed`, `d4-single-cell-sequencing` |

离线求值只证明草稿树在合成事实上可判定，不等于生产执行或 SqlBot 已生成总 SQL。
