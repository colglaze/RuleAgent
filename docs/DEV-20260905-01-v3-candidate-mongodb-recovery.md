# DEV-20260905-01：V3 候选 MongoDB 恢复实现

- 状态：`IMPLEMENTED`
- 日期：2026-09-05
- 来源需求：[REQ-20260905-01](REQ-20260905-01-v3-mongodb-recovery.md)
- 业务决策：[BIZ-20260905-01](BIZ-20260905-01-v3-candidate-mongodb-boundary.md)

## 数据模型

MongoDB Schema v4 创建 `rule_structure_candidates_v3`：

```text
_id = candidate_id
candidate_id
rule_set_id
contract_version = 3.0.0
catalog_digest
rule_block_sha256
payload_sha256
status = validatedBlockedCandidate
executable = false
stored_at
payload = {candidateId, source, catalog, candidate, status, executable}
```

`candidateId` 固定为 `<ruleSetId>@<ruleBlockSha256 前12位>-<catalogDigest 前12位>`。
canonical payload 使用 camelCase、UTF-8、排序键、紧凑 JSON、保留 Unicode 且禁止 NaN/Infinity。

## 组件

- 领域恢复 payload：交叉校验 candidate/catalog/source 身份和 V3 确定性门禁。
- Mongo repository：insert-only 保存、重复精确回读、hash 冲突拒绝和损坏记录 fail closed。
- 模块命令 `python -m scripts.persist_report_release_v3_recovery --reference-root <private repo>`：重建
  source-bound profile，初始化 Schema v4，保存并精确回读；只输出脱敏身份、计数和哈希。

## 测试

单元测试覆盖 candidate ID、canonical hash、交叉身份、幂等、冲突和损坏记录；migration integration
覆盖新集合及索引。最终先运行默认离线套件，再在当前配置 MongoDB 上执行 migration、首次恢复、重复
恢复和只读核对。
