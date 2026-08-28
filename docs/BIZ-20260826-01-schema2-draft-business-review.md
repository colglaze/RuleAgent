# BIZ-20260826-01：Schema 2.0 项目报告释放草稿业务审核

- 状态：`REVIEWED_WITH_BLOCKERS`
- 日期：2026-08-26
- 来源 REQ：[REQ-20260819-01](REQ-20260819-01-rule-contract-v2-agent2-handoff.md)
- 修订 REQ：[REQ-20260827-01](REQ-20260827-01-schema2-business-review-remediation.md)
- 修订 DEV：[DEV-20260827-01](DEV-20260827-01-schema2-business-review-remediation.md)
- 关联缺陷：[BUG-20260819-01](BUG-20260819-01-rule-ast-semantic-loss.md)、[BUG-20260826-01](BUG-20260826-01-schema2-business-review-blockers.md)
- 审核对象：`REPORT_RELEASE_ALL_001@20260824T080726492666Z-562eabd40e5a`
- 审核性质：只读业务审核；不批准、不发布、不执行、不修改不可变草稿或交接记录

## 1. 审核依据与方法

本次审核以精确版本导出的规则 JSON 为对象，并与下列证据交叉核对：

- 同一来源《项目报告释放规则》，规范化字符数 `7,501`，SHA-256 为 `562eabd40e5a5701fb9515499b542a6e2ff46056464621b1abb0a7c37f116e4d`；
- 精确规则导出文件 SHA-256 `993a527f94fb38281d9804cee3f507c9b25cdcaf7600e1af50df805f3ff57fdd`；
- `reviewed_import` profile 经 `enrich_candidate_v2` 后与导出规则正文完全一致；
- 规则正文包含 41 个事实、65 个条件节点、20 个案例和 41 个字段映射，其中 8 个为 `mapped + candidate`；
- 33 个非派生事实请求仍全部包含 `blocking` 不确定性，本次审核不解除任何阻断项。

审核只比较业务语义、事实粒度、参数、条件结构、案例覆盖和候选映射。没有连接 MongoDB、调用 DeepSeek、读取 SQL Server、生成 SQL 或写入任何业务集合。

## 2. 审核决定

该精确版本的顶层条件结构比历史 Schema `1.0.0` 草稿完整，金额公式、产品 `759` 两档、共同前置、直接放行路径、精确日期边界和合并报告去重均可在 AST 中复核。但是，事实粒度/参数、6 个金额/费用字段候选映射、`report.merge_flag` 值域和案例覆盖仍存在业务阻断问题。

因此本次结论为：

- **业务审核已执行，但草稿未通过业务批准。**
- 精确版本继续保持 `schemaVersion=2.0.0`、`status=draft`、`executable=false`。
- 当前 33 条 `fact_binding_handoffs` 继续保持不可变和 `blocking`，不得进入 SqlBot 候选生成。
- 当前版本不得原地修补。修正必须形成新的不可变 `ruleVersion`；若业务来源本身发生变化，还必须形成新的来源哈希。
- 本结论不授权规则发布、规则执行、SqlBot intake、SQL 生成或数据库元数据发现。

## 3. 41 个事实审核清单

“通过”仅表示当前事实的来源语义未发现差异，不代表查询绑定已批准。“待确认/待修正”必须在新版本形成前关闭。

| # | `factCode` | 结论 | 审核说明 |
| --- | --- | --- | --- |
| 1 | `task.status` | 通过 | `rwzt=19` 与共同前置一致。 |
| 2 | `task.data_usage_status` | 通过 | 原始值、可空和默认 `0` 与来源一致。 |
| 3 | `task.effective_data_usage_status` | 通过 | `coalesce(rwdsyzt,0)` 表达正确。 |
| 4 | `task.report_release_date` | 通过 | 空字符串或 `NULL` 的含义正确。 |
| 5 | `task.online_release_flag` | 通过 | 原始值及空值按 `1` 的定义正确。 |
| 6 | `task.effective_online_release_flag` | 通过 | `coalesce(sfxxsf,1)` 表达正确。 |
| 7 | `task.project_report_flag` | 通过 | 与 `zkqcbg` 的“或”关系由条件树表达。 |
| 8 | `task.periodic_report_flag` | 通过 | 与 `xmbg` 的“或”关系由条件树表达。 |
| 9 | `workflow.has_unfinished_report_release` | 待修正 | 来源按任务号 `sqlc` 查询两个流程字段，当前参数却是数值型 `taskId`；二者不能默认等同。 |
| 10 | `report.merge_flag` | 待修正 | `allowedValues=[0,1]` 与来源的“其他值”及案例使用值 `2` 冲突。 |
| 11 | `report.is_first_task_in_merge` | 通过 | `hbbglc + taskId` 粒度和组内最小 ID 语义一致。 |
| 12 | `product.id` | 通过 | 产品 `759` 分流语义正确。 |
| 13 | `product.type` | 通过 | 产品类型 `2/12` 分流语义正确。 |
| 14 | `order.amount` | 待确认 | 值属于订单，但声明粒度为 `formal_test_task`；字段候选只可保留为待审核输出提示。 |
| 15 | `amount.receipts_total` | 待确认 | `R` 定义正确；订单粒度与 `v_sto` 内部来源仍未确认。 |
| 16 | `amount.deposit_amount` | 待确认 | `D` 定义正确；订单粒度与 `v_sto` 内部来源仍未确认。 |
| 17 | `amount.prior_report_fee` | 待确认 | `B` 的任务范围和去重语义正确，但应确认订单粒度。 |
| 18 | `amount.transferred_task_fee` | 待修正 | `E` 的描述未固定主视图状态相关的预估回退口径，现候选辅助视图在无结算时可能使用不同数量规则。 |
| 19 | `amount.current_task_fee` | 待修正 | `C` 应采用主视图当前任务口径；现候选 `v_OrderFormaltestsettlement.zssyjsfy` 的空完成数量口径不同。 |
| 20 | `amount.merged_other_task_fee` | 通过 | `M` 的同订单、同合并报告、排除当前任务语义一致；物理绑定继续未决。 |
| 21 | `amount.required_fee` | 通过 | `F=B+E+C+M` 的结构化派生正确。 |
| 22 | `amount.task_fee` | 通过 | `T=E+C+M` 且不含 `B` 的结构化派生正确。 |
| 23 | `amount.transferred_estimated_fee` | 待修正 | 主视图承接转交任务的状态相关数量口径与候选辅助视图 `ctwgfy` 不同。 |
| 24 | `amount.formal_estimated_fee` | 待修正 | 主视图正式实验任务的状态相关数量口径与候选辅助视图 `zssywgfy` 不同。 |
| 25 | `amount.estimated_work_fee` | 待确认 | `W` 的加法正确，但它是订单级派生事实，当前粒度为 `formal_test_task`。 |
| 26 | `merged.other_order_fee_failure_count` | 待确认 | `R2/D2/B2/E2/M2/W2` 与押金门槛描述正确；值依赖 `mergeReportId + currentOrderId`，需确认 `merge_report_order` 类粒度而非 `merge_report_task`。 |
| 27 | `contract.current_order_meet_flag` | 待确认 | `dd_ismeet` 聚合含义正确，但属于订单粒度；描述中的“七个互斥分支”应改为“七个可选满足分支”。 |
| 28 | `contract.merged_orders_meet_flag` | 待确认 | 合并关联订单失败数为零的含义正确，粒度应由业务确认是合并报告而非合并报告任务。 |
| 29 | `order.framework_type` | 待确认 | 空值按 `1` 及 `0/2` 判断正确，事实属于订单粒度。 |
| 30 | `order.effective_framework_type` | 待确认 | 派生正确，粒度应跟随订单。 |
| 31 | `order.unit_attribute` | 待确认 | 空值按 `-1` 正确，事实属于订单粒度。 |
| 32 | `order.effective_unit_attribute` | 待确认 | 派生正确，粒度应跟随订单。 |
| 33 | `release.special_application_approved` | 待修正 | 来源按明细关联当前任务号，当前参数仅声明 `taskId`，需冻结真实业务键。 |
| 34 | `task.batch_release_flag` | 通过 | 空值按 `1`、值 `0` 直接放行的语义正确。 |
| 35 | `task.effective_batch_release_flag` | 通过 | `coalesce(sfplsf,1)` 表达正确。 |
| 36 | `release.raw_data_record_approved` | 待确认 | 当前事实合并了 `yssj=0` 与记录存在性；需确认这一复合事实及其任务关联键是稳定业务边界。 |
| 37 | `order.source_code` | 待确认 | `ddly=2` 语义正确，事实属于订单粒度。 |
| 38 | `invoice.has_unissued_positive_amount` | 通过 | 执行合同粒度、未开票和正金额语义一致。 |
| 39 | `task.completion_date` | 通过 | 定时释放日期基准正确。 |
| 40 | `runtime.current_date` | 待修正 | 数据库当天日期不依赖 `taskId`，也不属于 `formal_test_task` 粒度；必须明确为求值上下文还是独立事实。 |
| 41 | `task.business_scope_flag` | 通过 | 产品类型 `2/12` 且 `ywzfw=0` 的直接路径语义正确。 |

粒度审核的集中结论：14 个订单范围事实或派生事实当前声明为 `formal_test_task`，而 `FactBindingRequest 2.0.0` 会把 `grain` 作为 `declared` 语义交接。该问题不能依靠下游 `unresolved` 自动修正，必须在新规则版本中明确。

## 4. 65 个条件节点审核

条件树包含 `13 all + 9 any + 1 not + 42 compare = 65` 个节点。逐项与来源核对后，未发现下列核心拓扑再次发生 Schema `1.0.0` 的语义丢失：

- 共同前置与显式 `NOT` 未结束流程；
- 合并报告 `NULL/1/组内首条` 去重；
- 普通产品先执行跨订单费用门禁，再进入零金额、独立全额覆盖或合同金额路径；
- `R+0.1>=F`、`F=B+E+C+M`、`T=E+C+M` 和 `D>=W-R*20%`；
- 产品 `759` 的 `T<=100000 / 70%` 与 `T>100000 / 50%` 互斥分档；
- 特殊申请、批量释放、原始数据记录、订单来源、定时释放和业务组服务独立路径；
- 第 `60/75/180` 天使用日期相等，且第 75 天不要求未开票、第 180 天不限制 `T`。

条件树在当前事实抽象层面可接受，但不能单独抵消第 3 节中聚合事实定义、粒度和映射的问题。因此条件审核通过不等于整份草稿通过。

## 5. 20 个案例审核

- 20 个案例经当前确定性解释器均得到声明的 `14 pass / 6 fail`。
- 类别覆盖为：`normal=6`、`boundary=2`、`failure=5`、`mutuallyExclusiveBranch=2`、`null=1`、`timeBoundary=4`。
- `merge-deduplication-fail` 使用 `report.merge_flag=2`，但事实值域只允许 `[0,1]`；当前语义校验没有发现这一自相矛盾。
- 15 个条件节点从未在 20 个案例中同时出现 `pass` 与 `fail`：
  - 共同前置：`task-status-19`、`task-data-status-allowed`、`report-release-date-empty`、`online-release-enabled`、`report-type-eligible`、`project-report-zero`、`periodic-report-zero`；
  - 合并去重：`merge-flag-one`、`merge-first-task`；
  - 普通合同金额路径：`ordinary-nonframework-unit14`、`ordinary-nonframework`、`ordinary-unit14`、`ordinary-other-unit-or-framework-selector`、`ordinary-unit-not14`、`ordinary-framework`。
- 来源案例 1 的“非框架、单位属性 14、合同通过”路径没有形成实际通过 `ordinary-nonframework-unit14` 的案例；来源案例 6 的“当前订单通过但其他订单费用失败”也没有独立保留。

因此，20 个案例的已声明结果可复现，但案例集不足以支持业务批准。新版本应增加相互隔离的前置失败、周期报告替代路径、合并标志 `1`、合并组首条、单位属性 `14` 和框架协议路径案例，并保留来源案例语义。

## 6. 8 个候选映射审核

所有映射仍保持 `reviewStatus=candidate`。本表的“可保留”只表示字段含义与来源相符，不表示物理查询、筛选、粒度或 SQL 已批准。

| `factCode` | 当前候选 | 审核结果 | 原因 |
| --- | --- | --- | --- |
| `order.amount` | `v_OrderFormaltestsettlement.yhhje` | 可保留为候选 | 输出已按空值 `0` 表达订单金额；行粒度与标量化仍阻断。 |
| `amount.receipts_total` | `v_ReportDataReleaseRules.ddgldk_total` | 拒绝当前候选 | 主视图 `R` 直接聚合 `uf_dd_dt3/uf_dd_dt4`，候选字段依赖定义缺失的 `v_sto`，无法证明等价。 |
| `amount.deposit_amount` | `v_ReportDataReleaseRules.ddglyj` | 拒绝当前候选 | 主视图 `D` 直接聚合 `uf_dd_dt3` 的 `zxmk=1` 记录，候选字段依赖定义缺失的 `v_sto`，无法证明等价。 |
| `amount.transferred_task_fee` | `v_ReportDataReleaseRules.ctzjjsfy` | 拒绝当前候选 | 无确认结算时依赖辅助视图的预估数量口径，与主视图 `E` 的状态相关回退不等价。 |
| `amount.current_task_fee` | `v_OrderFormaltestsettlement.zssyjsfy` | 拒绝当前候选 | 来源明确区分主视图当前任务口径与该辅助视图的空完成数量口径。 |
| `amount.transferred_estimated_fee` | `v_ReportDataReleaseRules.ctwgfy` | 拒绝当前候选 | 辅助视图在完成数量为空时直接取下单数量，主视图还受任务状态影响。 |
| `amount.formal_estimated_fee` | `v_ReportDataReleaseRules.zssywgfy` | 拒绝当前候选 | 辅助视图在完成数量为空时直接取下单数量，主视图还受任务状态影响。 |
| `contract.current_order_meet_flag` | `v_ReportReleaseSealCondition.dd_ismeet` | 可保留为候选 | 聚合输出语义一致；订单键、行唯一性和筛选仍需下游元数据审核。 |

## 7. 新版本前置条件

在用户另行授权形成新版本前，至少需要：

1. 在独立修订任务中更新对应 REQ/DEV，冻结事实 `grain` 和参数角色，明确 `taskId`、任务号 `sqlc`、`orderId`、`mergeReportId` 与求值日期的边界；
2. 修正 `report.merge_flag` 值域，并让确定性校验检查案例值是否符合事实 `dataType/allowedValues/nullable`；
3. 把 6 个被拒绝的金额/费用映射恢复为 `unresolved`，或提供与主视图口径完全一致、可复核的新候选；
4. 补足第 5 节的分支案例，并重新执行 41 事实、65 条件和案例解释器审核；
5. 生成新的不可变 `ruleVersion`，继续保持 `draft`、`executable=false`；持久化仍需用户单独明确授权；
6. 不修改、覆盖或删除本次审核的 V2 版本、历史 V1 版本和现有 33 条交接记录。

## 8. 2026-08-27 修订授权

用户已明确授权按 [REQ-20260827-01](REQ-20260827-01-schema2-business-review-remediation.md) 和 [DEV-20260827-01](DEV-20260827-01-schema2-business-review-remediation.md) 修复本次审核阻断，并只生成未持久化的新 V2 草稿。授权明确排除 DeepSeek、MongoDB 规则/交接写入和现有不可变记录修改。

补读权威主视图后确认，`R/D` 的主视图聚合与 `v_ReportDataReleaseRules` 中依赖未知 `v_sto` 的同名输出不能证明等价。因此修订版将与另外 4 个费用候选一起恢复为 `unresolved`，只保留 `order.amount` 和 `contract.current_order_meet_flag` 两个可逐字段复核的候选。本项是更严格的安全收敛，不扩展字段目录或 SQL 能力。

## 9. 2026-08-27 修订产物

按已授权 [REQ-20260827-01](REQ-20260827-01-schema2-business-review-remediation.md) 形成了新版本 `REPORT_RELEASE_ALL_001@20260827T013225952760Z-562eabd40e5a`。它包含 42 个事实、67 个条件、31 个案例和 2 个保留候选映射，所有条件具备双向案例覆盖；34 个非派生事实请求均保持 blocking。

该版本只生成在本地 Git 忽略目录，没有写入 MongoDB。它关闭本审核提出的修订前置项，但尚未经过新的业务审核；本 BIZ 对旧精确版本的 `REVIEWED_WITH_BLOCKERS` 结论保持不变，新版本不得据此视为已批准、已发布或可执行。
