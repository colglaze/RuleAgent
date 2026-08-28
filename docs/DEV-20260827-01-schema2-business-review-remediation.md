# DEV-20260827-01：Schema 2.0 业务审核阻断修订方案

- 状态：`IMPLEMENTED`
- 日期：2026-08-27
- 来源 REQ：[REQ-20260827-01](REQ-20260827-01-schema2-business-review-remediation.md)
- 业务审核：[BIZ-20260826-01](BIZ-20260826-01-schema2-draft-business-review.md)
- 修复 BUG：[BUG-20260826-01](BUG-20260826-01-schema2-business-review-blockers.md)
- 前置 DEV：[DEV-20260819-01](DEV-20260819-01-rule-contract-v2.md)
- 完成证据：[PROG-20260827](PROG-20260827.md)

## 1. 版本与兼容策略

- 应用版本从 `0.8.0` 升级到 `0.9.0`；MongoDB Schema 保持 v3，不新增 migration。
- 规则 Schema 和事实交接契约仍分别为 `2.0.0`；本次不改变 JSON 形状，只修正规则实例并收紧既有语义校验。
- `scripts/reviewed_report_release_all_001.py` 保持不变，用于复现 2026-08-24 不可变规则正文。
- 新增 `scripts/reviewed_report_release_all_001_remediation.py`，从旧 profile 的新建 payload 深复制后执行显式、可审计的修订；不得静默修改旧 profile 常量或输出。
- reviewed import builder 增加显式 `reviewed_import_version` 参数，默认仍为 `reviewed-import-v1`；新离线导出明确传入 `reviewed-import-v2`。

## 2. 事实修订

### 2.1 粒度

以下事实改为 `grain=order`：

```text
order.amount
amount.receipts_total
amount.deposit_amount
amount.prior_report_fee
amount.transferred_task_fee
amount.transferred_estimated_fee
amount.formal_estimated_fee
amount.estimated_work_fee
contract.current_order_meet_flag
order.framework_type
order.effective_framework_type
order.unit_attribute
order.effective_unit_attribute
order.source_code
```

其他特殊粒度：

- `merged.other_order_fee_failure_count -> merge_report_order`；
- `contract.merged_orders_meet_flag -> merge_report`；
- `runtime.current_date -> rule_evaluation`；
- `report.is_first_task_in_merge` 与 `amount.merged_other_task_fee` 继续使用 `merge_report_task`。

### 2.2 参数

新增受控参数：

```text
taskNumber: string         # OA 正式实验任务号 sqlc
evaluationDate: date       # 本次规则求值采用的数据库日期
```

- `workflow.has_unfinished_report_release` 和 `release.special_application_approved` 改用 `taskNumber`。
- 新的 `release.has_approved_raw_data_record` 使用 `taskNumber`，因为正式视图按 `uf_yssjsf.zssyrwd = a.sqlc` 关联。
- `runtime.current_date` 使用 `evaluationDate`，不再声明 `taskId`。

### 2.3 原始数据直接路径

旧复合事实：

```text
release.raw_data_record_approved
```

替换为：

```text
task.raw_data_flag                    # a.yssj
release.has_approved_raw_data_record  # zt=1 and fssj>=2024-11-21 by taskNumber
```

条件树由一个布尔比较替换为：

```text
raw-data-record-path (all)
  raw-data-flag-zero (task.raw_data_flag == 0)
  approved-raw-data-record-exists (release.has_approved_raw_data_record == true)
```

因此事实数从 41 增至 42，非派生事实从 33 增至 34，条件节点从 65 增至 67。

## 3. 候选映射修订

精确主视图证据确认：

- 当前订单 `R/D` 来自主视图内 `uf_dd_dt3/uf_dd_dt4` 聚合，而 `v_ReportDataReleaseRules` 对应输出依赖定义缺失的 `v_sto`，不能证明等价；
- `E/C/W` 相关主视图子查询按任务状态决定空完成数量回退，辅助视图在完成数量为空时直接使用下单数量，不能证明等价。

因此下列 6 项改为 `unresolved`：

```text
amount.receipts_total
amount.deposit_amount
amount.transferred_task_fee
amount.current_task_fee
amount.transferred_estimated_fee
amount.formal_estimated_fee
```

只保留：

```text
order.amount -> v_OrderFormaltestsettlement.yhhje
contract.current_order_meet_flag -> v_ReportReleaseSealCondition.dd_ismeet
```

主视图 `v_sendreport_trigger` 不在当前四视图字段目录中，本任务不扩目录、不新增相似字段映射。

## 4. 案例输入语义校验

在 `validate_candidate_v2` 的案例循环中，解释条件树之前执行：

1. 未知事实检查；
2. `None` 只允许用于 `nullable=true` 的事实；
3. 值必须匹配声明的 `FactDataType`：布尔值不得冒充整数，金额/数值只接受非布尔数值，日期/日期时间必须是合法 ISO 字符串；
4. 非空 `allowedValues` 使用值相等校验；不在集合中时报告案例 ID 和 fact code；
5. 输入通过后才执行现有三值解释器。

错误继续聚合到 `SemanticValidationErrorV2.issues`，不修改候选或测试值。

现有“显式 null 失败”单元测试把目标事实改为 `nullable=true`，因为业务事实允许返回 null 后，条件 `nullPolicy=fail` 才是合法的规则案例。

## 5. 案例覆盖

在旧 20 个案例基础上新增 11 个隔离案例：

1. 任务状态失败；
2. 数据使用状态失败；
3. 报告释放日期非空失败；
4. 线上释放标志失败；
5. 两个报告标志均不满足；
6. 仅周期报告标志满足；
7. `merge_flag=1` 保留；
8. 其他合并标志但组内首条保留；
9. 非框架、单位属性 `14`、合同和全额覆盖分支；
10. 框架协议的 80% 分支；
11. 当前订单已满足但跨订单费用失败。

source-specific audit 对全部 67 个条件节点运行所有案例；任一节点缺少 `pass` 或 `fail` 即拒绝新 profile。

## 6. 离线导出

新增 `scripts/export_reviewed_report_release_remediation.py`：

```text
LocalDocumentReader
→ build remediated RuleCandidateV2
→ generic validation + source-specific audit
→ build_reviewed_rule_result(reviewed-import-v2)
→ safe payload validation
→ 34 FactBindingRequestV2
→ Pydantic + checked-in Draft 2020-12 Schema + safe payload validation
→ local JSON files + SHA-256 summary
```

脚本要求显式 `--document-root`、`--source`、`--generated-at` 和 `--output-dir`。它不导入 `Settings`、MongoDB 适配器或 DeepSeek 适配器，不提供 `--persist`。

## 7. 测试

- `validation_v2`：错误类型、非法 null、allowedValues 越界、合法日期/数值回归；
- 新 profile：精确事实/条件/案例/映射计数、粒度和参数、映射撤销、全部节点双向覆盖；
- reviewed import：默认 v1 追溯保持兼容，显式 v2 追溯生效；
- 新离线导出：使用临时目录和固定时钟，验证只生成两个文件且不需要配置或数据库；
- 新草稿事实请求：34 条、双重契约/安全门禁、全部 blocking；
- 旧 profile 与既有导出哈希回归保持不变。

默认测试继续排除 integration 和真实 Provider；本任务不运行 MongoDB integration，因为没有数据库实现或数据变更。

## 8. 实施结果

- `reviewed-import-v2` 修订 profile、案例输入门禁、31 个案例和 2 个保留候选映射已按本方案实现。
- 真实来源确定性导出版本为 `REPORT_RELEASE_ALL_001@20260827T013225952760Z-562eabd40e5a`，只写入 Git 忽略的本地产物目录。
- 导出结果为 42 个事实、67 个条件、31 个案例、34 个非派生事实请求；全部条件具备 `pass/fail` 双向覆盖，全部请求仍为 blocking。
- 离线默认测试、Ruff、严格 Mypy 和依赖完整性检查通过；未运行 MongoDB 或 Provider integration。
- 旧 profile 继续作为历史重建基线；历史交接测试从精确旧对象构建只读夹具，不绕过当前新写入门禁。
