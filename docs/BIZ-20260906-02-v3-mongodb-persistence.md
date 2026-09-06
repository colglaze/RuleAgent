# BIZ-20260906-02：V3 交付 MongoDB Schema v5 持久化业务决策

- 状态：`APPROVED_IMPLEMENTATION_AUTHORIZED`
- 日期：2026-09-06
- 来源需求：[REQ-20260906-01](REQ-20260906-01-v3-mongodb-persistence.md)
- 前置决策：[BIZ-20260905-02](BIZ-20260905-02-v3-agent2-handoff-contract.md)、
  [BIZ-20260906-01](BIZ-20260906-01-v3-blocker-business-confirmation.md)

## 决策

1. 用户于 2026-09-06 明确授权完成“RuleReader MongoDB Schema v5 持久化”的代码、自动化测试和
   文档同步，并允许把应用版本升级到 `0.12.0`。本决策延续
   [BIZ-20260905-02](BIZ-20260905-02-v3-agent2-handoff-contract.md) 第 6 条的独立集合设计与
   [BIZ-20260906-01](BIZ-20260906-01-v3-blocker-business-confirmation.md) 的确认边界，不替代
   任何旧决策的产品语义。
2. Schema v5 新增且仅新增 `rule_versions_v3` 与 `fact_binding_handoff_batches_v3`；V3 规则版本
   与事实交接 batch 保持 `draft`、`executable=false`、待审核，本决策不构成业务批准、发布或
   可执行授权。
3. 落库数据对象固定为当前 confirmed 产物
   `REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a` 及其 18 条
   `FactBindingRequest 3.0.0`；标志位 0/1 与 4/5 的编码差异仍必须在 SqlBot 物理绑定阶段复核。
4. confirmed reviewed-import profile 的 parserVersion 冻结为既有不可变产物使用的 `0.11.0`，
   不随应用包版本自动变化；既有产物身份不因本次版本升级改变。
5. 应用版本升级到 `0.12.0` 只影响服务元数据（`app_metadata.service_version`）与新解析的
   provenance 记录；不得把历史不可变产物中的 parserVersion 批量替换为 `0.12.0`。

## 授权边界

本决策授权工程实现、自动化测试与文档同步。以下事项不在本次授权内，数量保持为 0：

- 向当前真实 MongoDB 执行 migration 或写入任何数据；
- 调用 DeepSeek、连接 SQL Server、生成或执行 SQL；
- 修改 SqlBot 或其他仓库；
- 提交、推送、创建分支或 PR。

真实持久化执行需要在工程完成后由用户另行显式授权。

## 与被替代决策的关系

- [BIZ-20260905-02](BIZ-20260905-02-v3-agent2-handoff-contract.md) 第 3、7 条是 2026-09-05
  业务确认前的历史状态；其“未来 MongoDB 使用独立集合”的计划由本决策与
  [DEV-20260906-02](DEV-20260906-02-v3-mongodb-persistence.md) 落地，原文不修改（该文档末尾
  已补充后续状态说明）。
- [BIZ-20260906-01](BIZ-20260906-01-v3-blocker-business-confirmation.md) 授权边界中“Schema v5
  落库需单独授权”的条件，由本决策满足。

## 验收修订（2026-09-06，[BUG-20260906-03](BUG-20260906-03-v3-persistence-authorization-and-integrity-gaps.md)）

本修订收紧第 2 条的执行边界，不改写任何产品语义：

1. **运行时默认停留在 Schema v4**：普通服务、`rule-reader init-db` 与既有 V1/V2/V3-recovery
   用例不得创建 V3 持久化集合；只有显式 V3 持久化脚本可请求 Schema v5。当前真实数据库从未被
   本仓库访问，其 Schema 状态未知，任何文档不得声称真实数据库已经是 v5。
2. **唯一获批持久化对象**：脚本以 manifest 文件自身 SHA-256
   `0ef3af6939d7cdf9b206bd97d709c58f2308f87af625e082f88b03e35d20b0c4` 为信任锚，绑定
   ruleVersion `REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a`、
   18 条请求、20 个测试案例、ready=true、blocking=0、executable=false；其他任何 synthetic、
   自签名或再生 manifest 的产物不得被该脚本接受，也不提供绕过参数或环境开关。
