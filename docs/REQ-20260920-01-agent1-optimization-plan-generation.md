# REQ-20260920-01：Agent1 生成优化方案 3.1.0 完整交付

- 状态：`IMPLEMENTED`
- 日期：2026-09-20
- 对应决策：[BIZ-20260917-01](BIZ-20260917-01-optimization-plan-authority-agent1.md)
- 契约与持久化：[REQ-20260917-01](REQ-20260917-01-optimization-plan-rule-handoff.md)
- 对齐裁决：[BIZ-20260920-03](BIZ-20260920-03-optimization-plan-full-alignment.md)
- 技术方案：[DEV-20260920-03](DEV-20260920-03-agent1-optimization-plan-generation.md)

## 问题

优化方案 3.1.0 完整交付（报告 + 原始数据）目前由领域转译器和独立 build 脚本产出。Agent1
应用层（LangGraph / CLI）只能走 Schema 2.0 DeepSeek 解析或 Schema 3.0 单次
`--allow-provider` 结构生成，不能自己生成已落库的那套 3.1.0 产物。

## 范围

让 Agent1 **离线**生成与领域转译器相同的 Schema 3.1.0 完整交付：

1. LangGraph 编排：校验来源身份 → 生成报告交付 → 生成原始数据交付 → 用途/隔离门禁。
2. 生成器固定为已对齐的确定性转译器（`provider=reviewed_import`，
   `model=optimization-plan-translator-v1`）。
3. CLI 入口 `parse-optimization-plan`：从私有 source root 读取冻结相对路径，写出
   catalog/candidate/result/requests/manifest，打印脱敏摘要。默认不写 MongoDB；仅当显式传入
   `--persist` 时，对 `report/` 与 `data/` 做 insert-only 落库（与
   `scripts/persist_optimization_plan_v31_delivery.py` 同一仓储门禁）。
4. 既有 `scripts/build_optimization_plan_v31_delivery.py` 改为调用同一 Agent1 服务。

## 非目标

- 调用 DeepSeek 或任何在线模型生成 3.1.0 JSON。
- 把 3.1.0 接到 HTTP `POST /api/v1/rules/parse`（该入口保持 Schema 2.0）。
- 默认写入 MongoDB；`--persist` 不得覆盖历史 confirmed 版本，不得把规则标为 `executable=true`。
- 修改 SqlBot、连接 SQL Server。
- 把私有原文写入公开仓库、测试夹具、日志或摘要。

## 验收标准

1. Agent1 服务对合成 identity 产出报告 + 原始数据两套 3.1.0 交付，字段与
   `build_report_delivery` / `build_data_delivery` 一致。
2. 产物为 `draft` / `executable=false` / `purpose=optimization-plan-generation`。
3. 工作流不导入、不构造 DeepSeek 适配器；默认测试不读私有源文件、不连网、不写正式库。
4. 来源哈希不匹配、章节提取失败、身份字段非法时返回明确 `RuleParsingError`，不产出半套交付。
5. CLI 读取限制在 `--source-root` 内的冻结相对路径；路径穿越、缺失文件、错误编码显式失败。
6. CLI 默认不 persist；`--persist` 复用既有 insert-only 服务，失败时磁盘产物可保留且
   `mongodbWritten` 保持 false。

## 完成标准

自动化测试覆盖正常、失败和 CLI 参数；文档与进度已更新。完成不等于重新落库或 SqlBot 已能生成总 SQL。
