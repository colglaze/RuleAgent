# REQ-20260819-01：规则契约 2.0 与 Agent 2 事实交接

- 状态：`COMPLETED`
- 日期：2026-08-19
- 更新日期：2026-08-24
- 来源：用户确认统一 RuleReader / SqlBot 双 Agent 基线
- 前置需求：[REQ-20260818-03](REQ-20260818-03-rule-parser.md)
- 关联缺陷：[BUG-20260819-01](BUG-20260819-01-rule-ast-semantic-loss.md)
- 业务决策：[BIZ-20260819-01](BIZ-20260819-01-agent2-handoff-baseline.md)
- 技术方案：[DEV-20260819-01](DEV-20260819-01-rule-contract-v2.md)
- 后续持久化交接：[REQ-20260824-01](REQ-20260824-01-mongodb-fact-binding-handoff.md)

## 1. 背景

Schema `1.0.0` 能约束 JSON 形状，但不能确定性验证复杂金额公式、日期计算、存在性事实和测试案例。已归档《项目报告释放规则》因此出现结构合法但语义丢失的草稿。后续 SqlBot 作为 Agent 2 需要稳定、按事实的输入契约，不能直接把整份自然语言规则或 Schema `1.0.0` 草稿转换成 SQL。

## 2. 目标

- 发布破坏性升级的规则契约 Schema `2.0.0`，不改变旧 Schema `1.0.0` 的含义。
- 使用结构化表达式 AST 保存事实引用、字面量、算术和日期计算。
- 为事实声明种类、类型、粒度、参数、空值策略和可选派生表达式。
- 使用确定性解释器执行测试案例，拒绝与条件树不一致的候选。
- 从已校验 Schema `2.0.0` 草稿确定性导出按事实拆分的 `FactBindingRequest`。
- 将事实交接升级为可独立验证的 `FactBindingRequest 2.0.0` JSON Schema，完整表达生成候选 SQL 模板所需的查询语义；无法从规则草稿确定的内容必须显式标记为不确定，不能猜测。
- 保持已归档 Schema `1.0.0` 版本不可变且可精确回读，但禁止为其导出 Agent 2 请求。

## 3. 范围内

- 新增 Schema `2.0.0` Pydantic 领域模型、表达式与条件 AST。
- 新增事实类型：`source`、`aggregate`、`exists`、`derived`。
- 新增事实参数、业务粒度、空值策略、单位、枚举值和派生表达式。
- 校验事实/条件/测试 ID 唯一、表达式引用闭包、派生环、类型/操作符兼容、映射完整性和测试期望。
- 新增确定性三值解释器；验收案例只能得到明确 `pass` 或 `fail`。
- Rule Parsing Agent 改为请求 Schema `2.0.0` 候选，可信代码继续生成版本、来源和状态。
- 新增按规则版本导出 `FactBindingRequest[]` 的 HTTP 入口。
- 新增 Draft 2020-12 JSON Schema、正向/未决/反向/旧版样例以及离线兼容性测试。
- 在真实 Provider 尝试耗尽且用户逐次明确授权时，允许对指定来源执行受控 `reviewed_import`；该路径必须真实记录生成方式，并复用全部可信校验和持久化门禁。
- `FactBindingRequest 2.0.0` 明确业务实体与粒度、字段角色与来源候选、参数化筛选、聚合语义、时间范围、标量结果契约、来源证据和不确定性。
- `FactBindingRequest 1.0.0` 形状仅作为历史兼容夹具冻结保留；运行时默认和显式事实交接都只允许 `2.0.0`，不得因 SqlBot 尚未升级而降级输出。
- MongoDB 仓储同时读取 Schema `1.0.0` 与 `2.0.0`，新解析只写 `2.0.0`。

## 4. 范围外

- Agent 2 的模型调用、数据库元数据同步、SQL 生成、AST SQL 校验和执行。
- 事实注册中心、人工审核、模板发布和正式规则执行。
- 修改、覆盖或删除现有 Schema `1.0.0` 归档。
- 自动把旧草稿迁移成新草稿；同一来源必须重新解析并人工审核。

## 5. 验收标准

1. 新解析输出固定为 `schemaVersion=2.0.0`、`status=draft`、`executable=false`。
2. 条件比较的左右两侧均为结构化表达式，不能用描述文本代替决定性公式。
3. `derived` 事实必须有派生表达式，其他事实禁止携带派生表达式；派生依赖不得成环。
4. `requiredFacts` 必须等于条件直接引用与派生依赖的传递闭包；未使用事实和缺失事实均失败。
5. 操作符、表达式类型和值类型不兼容时失败。
6. 每个测试案例由确定性解释器执行，实际结果必须与 `expected` 一致且不能为 `indeterminate`。
7. 每个非 `derived` 事实恰好导出一个事实级 `FactBindingRequest`；请求包含规则引用、事实契约、条件使用位置、候选映射和事实级样例。
8. Schema `1.0.0` 版本仍可按原版本号回读；请求其事实交接时返回明确的不支持错误。
9. 默认测试不调用 DeepSeek、SQL 数据库或网络；真实 Provider 验收保持显式启用。
10. Ruff、Mypy、默认测试和 MongoDB integration 回归通过，文档与进度同步。
11. `FactBindingRequest 2.0.0` 提供带稳定 `$id` 的 [Draft 2020-12 JSON Schema](../contracts/fact-binding-request-2.0.0.schema.json)；Schema 使用 camelCase、封闭对象和必填版本常量，未知字段、漏字段和错误版本必须失败。
12. 每个 `2.0.0` 请求必须完整出现 `queryRequirements.entity/fields/filters/aggregation/timeRange/result`。字段物理来源、筛选完整性、聚合函数或时间边界不能确定时，使用受控 `resolutionStatus=unresolved`，不得省略或用 SQL/自由文本替代结构。
13. 每个请求必须携带源文件名、相对路径（可空）、完整内容哈希、字符数、解析时间、Parser/Prompt/Provider/模型版本，以及指向规则草稿 JSON Pointer 的证据清单；不确定性必须包含稳定编码、类别、字段路径、影响、原因和证据引用。
14. 旧 `FactBindingRequest 1.0.0` 样例保持原形状且能通过冻结模型；它必须被 `2.0.0` Schema 拒绝。现有 HTTP 端点无参数和 `contractVersion=2.0.0` 均返回新版，`contractVersion=1.0.0` 与未知版本返回 422；运行时不得继续输出旧版请求。
15. [正向显式未决样例](../contracts/examples/fact-binding-request-2.0.0.valid-unresolved.json)通过 `2.0.0` Schema；[反向漏字段样例](../contracts/examples/fact-binding-request-2.0.0.invalid-missing-time-range.json)失败；[旧版样例](../contracts/examples/fact-binding-request-1.0.0.legacy.json)仅通过冻结的 `1.0.0` 模型。领域导出的每个新版请求同时通过 Pydantic 与独立 JSON Schema 校验；默认验证不得访问网络、模型或数据库。
16. 使用 [BUG-20260819-01](BUG-20260819-01-rule-ast-semantic-loss.md) 指定的同一来源执行真实 DeepSeek 重解析；已授权尝试全部失败后，可按用户 2026-08-24 的明确决定改用一次受控 `reviewed_import`。无论候选来源为何，只有 Schema `2.0.0`、确定性校验及公式/互斥分支/空值/时间边界审计全部通过时，才保存为新的不可变 `draft`，并逐个为非 `derived` 事实导出 `FactBindingRequest 2.0.0`。
17. 受控导入的 Parser 元数据必须使用 `provider=reviewed_import`，记录导入契约版本和作者模型标识；不得标记为 DeepSeek。导入工具必须复核规范化来源哈希，且不得保存原始 Provider 响应或源文档正文。
18. 目标规则的测试案例必须带受控类别，并至少覆盖 `normal`、`failure`、`boundary`、`null`、`mutuallyExclusiveBranch` 和 `timeBoundary`；每个案例必须由同一确定性解释器得到明确结果。
19. 最终规则和事实请求不得携带可执行 SQL、数据库连接串、账号或密码。封闭对象之外，还必须对自由文本执行确定性敏感内容检查。

## 6. 安全边界

- `FactBindingRequest` 只描述业务事实和来源提示，不包含 SQL、数据库凭据或未受控表结构。
- `queryRequirements` 描述的是逻辑查询要求和未经批准的来源候选，不包含物理 JOIN 路径、任意 SQL 表达式或元数据快照内容。
- `declared` 只表示语义来自已校验规则草稿，`candidate` 只表示待审核来源提示；二者都不表示数据库映射或 SQL 已批准。
- 任一 SQL 必需语义为 `unresolved` 时必须生成 `blocking` 不确定性，后续消费者不得自行猜测为已确认值。
- `blocking` 不确定性允许规则草稿和事实请求持久化、回读及审核，但消费者必须在 SQL 候选生成前停止。
- 映射继续是 `candidate`；目录命中不等于模板已审核。
- Agent 2 只能生成候选 SQL，不能批准、发布或执行。
