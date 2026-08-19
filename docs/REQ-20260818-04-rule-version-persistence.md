# REQ-20260818-04：保存首个规则草稿版本

- 状态：`DONE`
- 日期：2026-08-18
- 来源：用户本次明确要求
- 前置需求：[REQ-20260818-03](REQ-20260818-03-rule-parser.md)
- 业务决策：[BIZ-20260818-06](BIZ-20260818-06-draft-rule-version-storage.md)
- 技术方案：[DEV-20260818-03](DEV-20260818-03-rule-version-persistence.md)

## 1. 背景

Rule Parsing Agent 已能把本地规则文本解析为带版本号的不可执行 JSON 草稿，但结果尚未持久化。用户要求先在 MongoDB 中保存一个版本。本需求建立最小、显式、不可变的草稿版本归档能力，并先保存《项目报告释放规则》的一个新解析版本。

## 2. 范围内

- MongoDB Schema 从 v1 迁移到 v2，新增 `rule_versions` 集合及必要唯一/查询索引。
- 完整保存通过 Schema 和语义校验的 `RuleParseResult`，同时保存可索引的规则编号、版本号、来源哈希、生成时间和入库时间。
- HTTP 解析请求通过 `persist=true` 显式入库；默认 `false`，普通试解析不写数据库。
- CLI 通过 `rule-reader parse --file <path> --persist` 显式入库；未提供参数时保持只解析行为。
- 提供按 `ruleVersion` 回读单个版本的 HTTP 接口，用于确认实际入库内容。
- 同一个 `ruleVersion` 重复保存必须幂等，不能覆盖或修改已有版本。
- 数据库失败返回脱敏的稳定错误，不返回“已保存”假象。
- 执行迁移后，实际解析并保存《项目报告释放规则》的一个 draft 版本，再从数据库回读校验。

## 3. 范围外

- 审批、发布、执行、启停、覆盖更新、删除和版本回滚。
- 规则列表、分页、全文检索和管理 UI。
- 把 `unresolved` 字段映射自动升级为已确认映射。
- 保存原始文档全文、Prompt、Provider 原始响应或任何密钥。
- Wiki、Agent 2 和其他长期模块。

## 4. 验收标准

- 空库和 Schema v1 数据库均可幂等升级到 Schema v2；`app_metadata` 的 schema version 正确更新为 2。
- `rule_versions` 至少具备唯一 `rule_version` 索引、`rule_id + generated_at` 查询索引和 `source_sha256` 查询索引。
- 入库文档 `_id` 与 `rule_version` 均使用可信代码生成的 `ruleVersion`；业务 JSON 保持 Schema `1.0.0`、`status=draft`、`executable=false`。
- `POST /api/v1/rules/parse` 在 `persist=true` 时只在解析和校验成功后入库；默认请求不入库。
- `GET /api/v1/rules/versions/{ruleVersion}` 能回读完整业务 JSON 和 `storedAt`；不存在时返回 404。
- CLI 的 `--persist` 使用同一仓储实现，stdout 仍只输出规则 JSON，不混入日志或数据库回执。
- 重复保存同一版本不会生成第二条记录，也不会修改 `stored_at` 或业务文档。
- 自动化测试覆盖 v2 迁移、索引、保存、重复保存、回读、默认不保存和显式保存。
- Ruff、Mypy、默认测试和 MongoDB integration 测试通过；真实首版记录可按版本号回读。
