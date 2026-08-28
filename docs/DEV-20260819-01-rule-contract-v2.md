# DEV-20260819-01：规则契约 2.0 与事实绑定导出

- 状态：`IMPLEMENTED`
- 日期：2026-08-19
- 更新日期：2026-08-24
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
- Schema/语义重试反馈最多携带 100 条字段路径；发生校验重试时把上一份未通过候选作为 `previousCandidate` 回传给同一 Provider，请模型返回完整修正版。可信代码不补字段，修正版仍从 JSON Schema、语义校验和确定性解释器重新开始验证。

## 5. FactBindingRequest

### 5.1 版本策略

- `FactBindingRequest 1.0.0` 冻结为历史兼容形状，只供静态样例、旧载荷解析和兼容性测试使用；应用层及 HTTP 不再导出它。
- 补齐必填 SQL 查询语义是破坏性变更，新契约版本固定为 `2.0.0`；规则文档 `schemaVersion=2.0.0` 与事实交接 `contractVersion=2.0.0` 是两个独立版本轴。
- 原端点保留 `contractVersion` 查询参数但仅接受 `2.0.0`，默认也是 `2.0.0`；`1.0.0` 和未知版本由 FastAPI/Pydantic 返回 422。
- 新版静态 Schema 位于 [contracts/fact-binding-request-2.0.0.schema.json](../contracts/fact-binding-request-2.0.0.schema.json)，使用 JSON Schema Draft 2020-12、稳定 `$id`、camelCase、`additionalProperties=false` 和必填常量字段。

### 5.2 旧版形状

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

### 5.3 `FactBindingRequest 2.0.0`

```text
FactBindingRequestV2
  contractVersion: "2.0.0"
  status: "candidate"
  requestId: ruleVersion + "#" + factCode
  ruleRef
  fact: non-derived binding fact contract
  queryRequirements
    entity: logical entityType/grain/keyParameters
    fields[]: value/entityKey/filter/groupBy/time roles and optional source candidate
    filters: structured parameter/literal predicates + completeness
    aggregation: none/precomputed/compute/exists/unresolved
    timeRange: none/asOf/between/unresolved with structured boundaries
    result: fact_value scalar result contract
  usages[]
  mappingCandidate
  examples[]
  provenance: source/parser/generatedAt/evidence[]
  uncertainties[]
  targetDialect: "sqlserver"
  requiresMetadataSnapshot: true
  tempTableAllowed: false
```

字段语义：

- `entity.entityType` 是规则适用的逻辑业务实体，`grain` 是每个事实值所属粒度；`keyParameters` 只引用 `fact.parameters[].name`。当前草稿不能证明哪些查询参数是实体键时，列表为空且 `keyResolutionStatus=unresolved`；这些字段不声明物理表或主键列。
- `fields[]` 至少包含一个 `role=value` 的 `factValue`，并为当前事实参数生成待绑定的 `filter` 字段要求；只有已明确属于实体标识的字段才能使用 `entityKey`。`sourceCandidate` 只允许关系名和字段名，不携带 schema、JOIN 或 SQL 表达式。
- `filters.items[]` 使用字段引用、受控操作符和 `parameter/literal` 值；`completeness` 明确这些筛选是否已覆盖事实定义。事实参数确定性导出为参数筛选，但物理字段未知时保持 `unresolved`。
- `aggregation` 区分直接值、预聚合字段、需计算聚合、存在性和未决语义；只有 `compute` 可以声明受控聚合函数、输入字段和分组字段。
- `timeRange` 必须始终出现。确认不需要时间条件时使用 `none/notApplicable`；有明确边界时使用 `asOf` 或 `between`；现有草稿没有决定性时间语义时使用 `unresolved`，不能把字段留空后视作“不需要”。
- `result` 固定要求单行单列别名 `fact_value`，数据类型、可空性、空值策略和单位与 `fact` 一致。
- `provenance.evidence[]` 以 JSON Pointer 指回不可变规则草稿中的事实、条件、映射和案例；请求的来源哈希必须与 `ruleRef.sourceSha256` 一致。
- `uncertainties[]` 使用稳定 `code/category/fieldPath/impact/reason/evidenceIds`。所有会影响 SQL 正确性的未决项均为 `impact=blocking`。

### 5.4 现有 Schema 2.0 草稿的确定性映射

- 规则 `entityType`、事实 `grain/parameters/dataType/nullPolicy` 和测试案例可直接声明为 `declared`。
- 精确命中的 `fieldMappings` 只形成 `candidate` value-field 来源；`sourceExpression` 永不进入交接。
- 参数生成等值参数筛选和对应 `filter` 字段要求；由于当前规则契约没有参数角色和物理键字段，实体键、字段与筛选保持 `unresolved` 并生成阻塞项。
- `source` 事实声明 `aggregation.mode=none`；映射命中的 `aggregate` 事实声明 `precomputed/candidate`，否则聚合语义未决；`exists` 声明存在性模式，但筛选完整性仍需独立确认。
- 当前规则契约没有事实级时间字段/边界，因此新版导出必须生成 `timeRange.mode=unresolved` 和阻塞项。该限制通过不确定性显式暴露，不在 RuleReader 中新增 SQL 或数据库元数据推断。

HTTP：

```text
GET /api/v1/rules/versions/{ruleVersion}/fact-binding-requests
```

- 不带查询参数或使用 `?contractVersion=2.0.0` 时均返回新版请求数组；
- `?contractVersion=1.0.0` 和未知版本返回 422，运行时不提供降级输出；
- v1 返回 409 和 `RULE_SCHEMA_UNSUPPORTED_FOR_BINDING`；
- 未找到返回 404；仓储不可用返回 503。

## 6. 测试

- v2 模型形状、表达式形状、派生环、闭包、类型和映射测试；
- `R+0.1>=B+E+C+M` 与产品 `759` 分档回归；
- 测试案例实际结果不一致时失败；
- v1 精确回读和 v1 导出拒绝；
- v2 持久化/回读与事实交接 HTTP；
- 默认测试使用固定候选，不调用 DeepSeek。
- HTTP 回归验证默认和显式调用只返回 `2.0.0`，旧版及未知版本均失败；旧模型仅验证历史样例仍可识别。
- 使用 dev-only `jsonschema` Draft 2020-12 validator 检查 Schema 本身、正向显式未决样例、反向漏字段样例和旧版不兼容样例；该依赖不进入运行时锁文件。
- 测试静态 Schema 与 Pydantic 生成 Schema 的关键版本、必填和封闭对象约束一致，并验证真实导出载荷同时通过两套验证器。

Phase 1.8 实施时，`jsonschema==4.26.0` 仅加入开发依赖和 `requirements-dev.lock`。Phase 1.10 的不可变 MongoDB 写入把仓库内静态 Schema 校验提升为运行时写入门禁，因此该依赖已按 [DEV-20260824-01](DEV-20260824-01-mongodb-fact-binding-handoff.md) 精确固定到运行时依赖和 `requirements.lock`。Schema 仍由 Pydantic 权威模型生成；独立 validator 用于阻止静态契约与写入载荷漂移。版本与许可依据见 [PyPI 项目页](https://pypi.org/project/jsonschema/)。

## 7. 受控 reviewed import

用户于 2026-08-24 在两批真实 DeepSeek 尝试均耗尽后明确授权以下一次性关闭路径：

- 新增供应商无关的应用层 `build_reviewed_rule_result`，接收已经显式评审的 `RuleCandidateV2` 和原始来源文本；它不调用模型、网络或数据库。
- 来源文本使用与 LangGraph workflow 相同的 BOM/换行/首尾空白规范化和 SHA-256 算法；结果继续由可信代码生成不可变 `ruleVersion`、UTC 时间、`draft` 和 `executable=false`。
- Parser 元数据使用 `provider=reviewed_import`、`promptVersion=reviewed-import-v1` 和真实作者模型标识；不得复用 `provider=deepseek` 冒充 Provider 输出。
- `RuleTestCaseV2` 增加受控 `category`，目标规则专项审计强制六类案例齐全。通用语义校验仍逐个执行案例，不根据类别跳过执行。
- V2 最终映射不再携带目录 `sourceExpression`；只保留候选视图/字段、启用状态和审核状态。自由文本中的可执行 SQL 或凭据模式由确定性校验拒绝。
- 一次性导入工具必须按顺序完成候选 Pydantic → 领域语义/解释器 → `REPORT_RELEASE_ALL_001` 专项结构审计 → 最终规则 Pydantic → 每个非派生事实请求 Pydantic →独立 Draft 2020-12 Schema。全部通过后才能调用现有不可变仓储；随后必须精确回读同一版本并重新导出、复验全部请求。
- 该工具不进入公开 HTTP/API，不新增 Agent 2、SQL、目标库元数据或规则发布能力；持久化仍需显式 `--persist`。
