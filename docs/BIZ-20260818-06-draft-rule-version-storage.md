# BIZ-20260818-06：草稿规则版本归档策略

- 状态：`ACCEPTED`
- 日期：2026-08-18
- 来源 REQ：[REQ-20260818-04](REQ-20260818-04-rule-version-persistence.md)
- 影响范围：MongoDB Schema、规则解析 HTTP/CLI 入口和版本回读

## 1. 决策

1. 当前保存的是“解析草稿归档”，不是正式发布规则库；持久化不改变 `draft` 和 `executable=false`。
2. 持久化必须显式选择。HTTP 使用 `persist=true`，CLI 使用 `--persist`，默认解析仍不产生数据库业务记录。
3. `rule_versions` 中每条记录不可变，使用 `ruleVersion` 同时作为 MongoDB `_id` 和业务唯一键。
4. 同一版本重复请求按幂等成功处理；已有记录不覆盖、不更新时间，也不进行 upsert 修改。
5. 集合保存完整 `RuleParseResult`，另冗余保存少量索引字段；MongoDB 记录不保存原始规则文本、Prompt 或 Provider 原始响应。
6. 首条实际记录选择用户最先提供的《项目报告释放规则》。该记录仍包含候选映射，未确认项保持 `unresolved`。
7. 当前只支持按精确版本号回读，不提供列表、模糊搜索、更新或删除接口。

## 2. 文档结构

```text
rule_versions
  _id: ruleVersion
  rule_version: string
  rule_id: string
  source_sha256: string
  schema_version: string
  parser_version: string
  status: "draft"
  executable: false
  generated_at: UTC datetime
  stored_at: UTC datetime
  document: RuleParseResult (camelCase)
```

MongoDB 内部索引字段使用 snake_case；对外业务 JSON 继续使用既有 camelCase 契约。

## 3. 失败与安全策略

- 只有解析、Schema 校验和语义校验全部成功后才允许保存。
- MongoDB 写入或回读失败转换为脱敏的 `RULE_PERSISTENCE_UNAVAILABLE`，不泄露 URI、凭据或数据库原始错误。
- 精确版本不存在返回 `RULE_VERSION_NOT_FOUND`。
- 若唯一键已存在，仓储回读已有记录并返回，不修改已有内容。

## 4. 官方依据

- [PyMongo Insert Documents](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/insert/)
- [MongoDB Unique Indexes](https://www.mongodb.com/docs/manual/core/index-unique/)
