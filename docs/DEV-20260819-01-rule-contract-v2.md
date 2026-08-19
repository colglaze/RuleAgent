# DEV-20260819-01：规则契约 2.0 与事实绑定导出

- 状态：`IMPLEMENTED`
- 日期：2026-08-19
- 来源 REQ：[REQ-20260819-01](REQ-20260819-01-rule-contract-v2-agent2-handoff.md)
- 关联 BIZ：[BIZ-20260819-01](BIZ-20260819-01-agent2-handoff-baseline.md)
- 修复 BUG：[BUG-20260819-01](BUG-20260819-01-rule-ast-semantic-loss.md)

## 1. 兼容策略

- 保留 `domain.rules.models` 中 Schema `1.0.0` 模型，作为旧归档只读契约。
- 新增 `domain.rules.v2`，定义 Schema `2.0.0` 候选和最终结果。
- 新增版本化文档联合类型与解析函数；使用 `schemaVersion` 选择模型。
- Rule Parsing workflow 只生成 Schema `2.0.0`；仓储 `save/get` 接受两个版本。
- 事实绑定导出只接受 Schema `2.0.0`，旧版本返回稳定错误码。

## 2. Schema 2.0 核心结构

```text
RuleParseResultV2
  schemaVersion: "2.0.0"
  trusted version/source/parser/status metadata
  rule
    ruleId/title/scope/sourceViews
    entityType
    requiredFacts[]
    rootCondition
    testCases[]
    fieldMappings[]
    review text fields
```

`RequiredFactV2` 至少包含：

- `factCode`：稳定的点分领域编码；
- `factKind`：`source/aggregate/exists/derived`；
- `dataType`、`nullable`、`nullPolicy`；
- `grain`：业务实体粒度；
- `parameters[]`：查询该事实所需业务参数；
- 可选 `unit/allowedValues/defaultValue`；
- `derived` 专用 `derivation` 表达式。

## 3. 表达式与条件 AST

表达式节点封闭为：

- `fact`、`literal`；
- `add`、`subtract`、`multiply`、`divide`；
- `coalesce`；
- `dateAdd`。

条件节点封闭为 `all/any/not/compare`。`compare` 使用 `left`、受控操作符和可选 `right`；空值类操作符不携带 `right`。决定性逻辑不得只存在于 `description`。

## 4. 确定性校验和解释器

- 收集条件表达式引用，并展开 `derived` 事实依赖；最终闭包必须与 `requiredFacts` 完全一致。
- 派生图执行 DFS 检测未知引用和环。
- 表达式执行使用明确的缺失值标记；布尔组合使用 `pass/fail/indeterminate` 三值逻辑。
- 数值运算使用十进制语义，日期使用 ISO 8601 和显式单位。
- 每个测试案例执行完整条件树；结果为 `indeterminate` 或与期望不符时拒绝候选。
- 映射目录继续只允许精确的 `viewName + viewField` 命中。

## 5. FactBindingRequest

```text
FactBindingRequest
  contractVersion: "1.0.0"
  status: "candidate"
  ruleRef: ruleId/ruleVersion/schemaVersion/sourceSha256
  fact: full RequiredFactV2
  usages[]: conditionId/path/operator/expressionSide
  mappingCandidate
  examples[]: testCaseId/value/expectedRuleResult
  targetDialect: "sqlserver"
  requiresMetadataSnapshot: true
  tempTableAllowed: false
```

只为非 `derived` 事实导出请求。`mapped` 记录仍随请求传递，供 Agent 2 判断是否复用候选视图；它不代表正式 Provider 已存在。

HTTP：

```text
GET /api/v1/rules/versions/{ruleVersion}/fact-binding-requests
```

- v2 成功返回请求数组；
- v1 返回 409 和 `RULE_SCHEMA_UNSUPPORTED_FOR_BINDING`；
- 未找到返回 404；仓储不可用返回 503。

## 6. 测试

- v2 模型形状、表达式形状、派生环、闭包、类型和映射测试；
- `R+0.1>=B+E+C+M` 与产品 `759` 分档回归；
- 测试案例实际结果不一致时失败；
- v1 精确回读和 v1 导出拒绝；
- v2 持久化/回读与事实交接 HTTP；
- 默认测试使用固定候选，不调用 DeepSeek。
