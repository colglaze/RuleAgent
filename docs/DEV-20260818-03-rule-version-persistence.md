# DEV-20260818-03：MongoDB 规则草稿版本持久化

- 状态：`IMPLEMENTED`
- 日期：2026-08-18
- 来源 REQ：[REQ-20260818-04](REQ-20260818-04-rule-version-persistence.md)
- 关联 BIZ：[BIZ-20260818-06](BIZ-20260818-06-draft-rule-version-storage.md)

## 1. 模块与依赖方向

```text
application/rule_versions/ports.py       仓储端口、保存结果和脱敏错误
infrastructure/rule_versions.py          MongoDB 仓储实现
infrastructure/migrations.py             Schema v2 集合与索引
api/routes.py                             显式保存和精确版本回读
cli.py                                    --persist 入口
```

API 和 CLI 只调用应用端口，不直接拼写 MongoDB 查询。领域 JSON 模型继续不导入 PyMongo；基础设施负责 Pydantic/BSON 转换。

## 2. Schema v2 迁移

- `LATEST_SCHEMA_VERSION = 2`。
- v1 migration 固定写入版本 1，不能引用未来的 latest 常量。
- v2 创建 `rule_versions` 并建立：
  - `uq_rule_versions_rule_version`：`rule_version` 唯一；
  - `ix_rule_versions_rule_id_generated_at`：`rule_id` 升序、`generated_at` 降序；
  - `ix_rule_versions_source_sha256`：`source_sha256` 升序。
- v2 完成后把 `app_metadata.database_schema.schema_version` 更新为 2。
- 迁移继续保持从空库执行、从 v1 升级和重复执行幂等。

## 3. 仓储契约

```text
save(result: RuleParseResult) -> SavedRuleVersion
get(rule_version: str) -> StoredRuleVersion | None
```

`save` 使用 `insert_one` 创建不可变记录。发生唯一键冲突时回读原记录并返回 `inserted=false`；不得使用会覆盖业务字段的 update/replace。保存和回读都重新用 `RuleParseResult` 校验内嵌文档。

## 4. HTTP 与 CLI

- `ParseRuleRequest` 新增 `persist: bool = false`。
- `POST /api/v1/rules/parse`：解析成功后，只有 `persist=true` 才调用仓储；保存失败时返回 503。
- `GET /api/v1/rules/versions/{ruleVersion}`：返回 `ruleVersion`、`storedAt` 和完整 `document`；不存在返回 404。
- `rule-reader parse --file <path> --persist`：先确保 MongoDB Schema v2 可用，再解析并保存；stdout 保持既有规则 JSON。

## 5. 测试与 DoD

- 单元测试使用内存 Fake Repository，验证 API 默认不保存、显式保存和精确回读。
- MongoDB integration 在随机测试库验证 v2 迁移、全部索引、首次保存、重复保存不覆盖、回读和记录计数。
- 执行 Ruff、Mypy、默认测试和 MongoDB integration。
- 在正式 `rule_reader` 数据库执行 v2 迁移，解析《项目报告释放规则》并显式保存，随后按版本号回读安全摘要。
- 同步 README、REQ、DEV、实施、进度和 PROG 文档。
