# RuleReader 产品需求文档

- 状态：`RULE_SCHEMA_V3_SLICE_1_2_IMPLEMENTED`
- 更新日期：2026-09-03
- 当前需求：[REQ-20260818-01](REQ-20260818-01-vibe-coding-bootstrap.md)
- 后端骨架需求：[REQ-20260818-02](REQ-20260818-02-backend-skeleton.md)
- 规则解析需求：[REQ-20260818-03](REQ-20260818-03-rule-parser.md)
- 草稿版本持久化需求：[REQ-20260818-04](REQ-20260818-04-rule-version-persistence.md)
- 规则契约 2.0 与事实交接需求：[REQ-20260819-01](REQ-20260819-01-rule-contract-v2-agent2-handoff.md)
- MongoDB 不可变事实交接需求：[REQ-20260824-01](REQ-20260824-01-mongodb-fact-binding-handoff.md)
- Schema 2.0 业务审核修订需求：[REQ-20260827-01](REQ-20260827-01-schema2-business-review-remediation.md)
- Rule Schema 3.0 需求：[REQ-20260902-01](REQ-20260902-01-rule-contract-v3-agent2-ready-handoff.md)
- 当前范围决策：[BIZ-20260818-01](BIZ-20260818-01-phase1-local-documents.md)
- 技术栈决策：[BIZ-20260818-02](BIZ-20260818-02-python-langgraph.md)
- 运行时与模型决策：[BIZ-20260818-03](BIZ-20260818-03-python311-deepseek.md)
- JSON 与映射决策：[BIZ-20260818-05](BIZ-20260818-05-rule-json-version-mapping.md)
- 草稿版本归档决策：[BIZ-20260818-06](BIZ-20260818-06-draft-rule-version-storage.md)
- 双 Agent 交接决策：[BIZ-20260819-01](BIZ-20260819-01-agent2-handoff-baseline.md)
- MongoDB 交接决策：[BIZ-20260824-01](BIZ-20260824-01-mongodb-fact-binding-handoff.md)
- 长期方案：[项目释放规则治理与诊断系统最终方案](../project_release_double_agent_solution.md)

## 1. 产品愿景

RuleReader 的长期目标是把业务释放规则转换为可版本化、可审核、可测试、可解释的结构化规则，并由确定性后端能力执行和追踪。长期架构包含规则治理、事实映射、规则执行和结果解释等模块，具体以根目录总体方案为参考。

当前里程碑不实现长期闭环，只验证可靠规则解析、显式保存不可执行草稿版本，以及向独立 Agent 2 导出并不可变持久化事实级请求的核心能力。

在规则解析前先完成 Phase 1.0 后端骨架：服务可启动、配置可读取、MongoDB 可连接并完成基础设施 Schema 初始化。

## 2. 第一阶段目标

业务规则维护者可以提供符合约定模板的本地 Markdown 文档；Rule Parsing Agent 将其转换为可校验、可追溯、待人工审核的结构化规则草稿。系统必须在无法可靠解析时明确失败，不能产生看似合法但无法追溯或语义不完整的规则。

## 3. 目标用户与使用流程

目标用户：负责维护和审核项目释放规则的业务人员或开发人员。

基本流程：

1. 用户在受控目录中维护 Markdown 规则文档。
2. 用户触发单文件或显式文件集合的规则解析。
3. Agent 提取规则结构、依赖事实和测试案例。
4. 系统执行 Schema 与语义校验。
5. 成功时输出待审核草稿及来源信息；失败时输出可定位的问题，不发布任何规则。
6. 用户可显式选择把校验通过的草稿作为不可变版本存入 MongoDB，并按精确版本号回读。
7. 用户可从 Schema `2.0.0` 版本导出非派生事实的绑定请求，交给独立 SqlBot 做后续校验。
8. 用户可显式把已持久化 Schema `2.0.0` 版本的事实请求写入 RuleReader 所有、SqlBot 只读的不可变 MongoDB 交接集合。

## 4. 功能需求

### FR-01 本地文档输入

- 第一阶段只支持本地 Markdown。
- 只读取配置根目录内的显式文件或文件集合。
- 空文件、不可读文件、越界路径和不支持的编码必须返回明确错误。

### FR-02 规则信息提取

解析内容至少覆盖规则编号、适用范围、生效条件、例外条件、未通过原因、处理建议、责任角色和测试案例。缺失必填信息或存在无法消解的歧义时，不得静默猜测。

### FR-03 结构化草稿

- 输出符合约定 JSON Schema 的规则草稿。
- 条件使用受控节点和操作符表达。
- 输出 `requiredFacts`，并保持条件引用与事实清单一致。
- 草稿必须明确标识为不可发布、不可执行的状态。

### FR-04 校验与错误反馈

- 对模型输出执行 JSON Schema 校验。
- 对重复规则编号、未知节点/操作符、类型不匹配、空条件、事实引用不一致等执行语义校验。
- 错误应包含可定位字段、错误类别和可理解说明。

### FR-05 可追溯性

解析结果至少关联源文件相对路径、内容哈希、解析时间以及解析器或 Prompt 版本。不得用模型生成的摘要替代原始来源引用。

### FR-06 测试案例

保留文档中已有案例，并为明确规则生成必要的正向、反向和边界案例草稿。生成案例同样需要校验并接受人工审核。

### FR-07 版本与字段映射

- 每次解析生成包含规则编号、UTC 时间戳和源内容哈希前缀的 `ruleVersion`。
- 输出携带 JSON Schema、Parser 和 Prompt 版本，不依赖模型生成版本元数据。
- 每个必需事实都必须有一条字段映射记录；四视图无法确认的字段显式标记为 `unresolved`。
- 所有解析结果保持 `draft` 且不可执行，版本号不代表已审批或已发布。

### FR-08 草稿版本归档

- 默认解析不写数据库；只有 HTTP `persist=true` 或 CLI `--persist` 才保存。
- 每个 `ruleVersion` 在 MongoDB 中唯一且不可变，重复保存同一版本必须幂等。
- 保存完整结构化草稿和必要索引元数据，但不保存原始文档正文、Prompt 或 Provider 原始响应。
- 支持按精确 `ruleVersion` 回读；归档不代表规则已审核、发布或可执行。

### FR-09 Schema 2.0 与事实交接

- 新解析使用结构化表达式、事实种类、粒度、参数、空值策略和派生依赖，不能把决定性公式只放在描述文本中。
- `requiredFacts` 必须等于条件引用和派生依赖的传递闭包；规则测试案例必须由确定性解释器执行并与期望一致。
- 案例输入必须与事实声明的 `dataType`、`nullable` 和非空 `allowedValues` 一致；非法输入不得先进入解释器或被自动转换。
- Schema `1.0.0` 历史版本保持不可变、可回读，但不能导出 Agent 2 请求。
- 每个非 `derived` 事实导出一个 camelCase `FactBindingRequest`；请求不包含 SQL、数据库凭据或目标库元数据。

### FR-10 可验证的事实绑定契约

- `FactBindingRequest 2.0.0` 必须提供独立 Draft 2020-12 JSON Schema，并使用必填、封闭的 camelCase 对象；规则 Schema 与事实交接契约分别版本化。
- 查询要求必须明确逻辑实体与粒度、字段角色与来源候选、参数化筛选、聚合、时间范围和标量结果；无法从规则草稿确定的内容仍须出现并标记为 `unresolved`。
- 请求必须携带完整来源/Parser 追溯、指回规则草稿的证据引用，以及可机读的阻塞或告警不确定性；不得把描述文本或候选目录表达式当成 SQL 设计。
- `FactBindingRequest 1.0.0` 仅作为历史兼容夹具保留；运行时无参数和显式调用均只输出 `2.0.0`，旧版与未知版本请求明确失败。SqlBot 尚未升级 intake 不触发降级。

### FR-11 MongoDB 不可变事实交接

- `fact_binding_handoffs` 由 RuleReader 创建、校验和唯一写入；SqlBot 只读，不得修改或迁移该集合。
- 每个非 `derived` 事实使用 `<ruleVersion>#<factCode>` 作为 `_id` 和 `requestId`，保存完整 camelCase `FactBindingRequest 2.0.0`、canonical payload SHA-256 和首次 UTC 创建时间。
- 交接只能从 `rule_versions` 精确回读且通过 `RuleParseResultV2` 校验的记录生成；Schema `1.0.0`、内存候选、导出文件和源文档不能直接写入。
- 相同 request ID 与哈希重复写入幂等且不更新时间；不同哈希必须失败并禁止覆盖。
- 写入前逐条通过 Pydantic、仓库内 Draft 2020-12 Schema 和安全文本门禁；blocking uncertainties 原样保留。

### FR-12 DeepSeek 调用治理

- 可重试 Provider/候选失败必须在下一次尝试前执行有上限的指数退避；首次调用、不可重试失败和最终失败后不得额外等待。
- 成功草稿和最终错误必须提供安全调用审计，包括 RuleReader request ID、尝试次数、逐次结果、Provider completion ID 和可获得的 token usage；不得返回原始 Provider 响应。
- HTTP 和 CLI 可接受显式幂等键。同一服务进程内，同键同解析身份合并在途调用并精确重放成功结果；同键异身份必须在调用 Provider 前冲突失败。
- 原始幂等键、来源正文、Prompt、API Key 和连接串不得进入日志或审计；只允许保存幂等键 SHA-256。
- 进程内幂等不承诺跨进程、跨 worker 或跨重启一致性，也不新增 MongoDB 审计或幂等集合。

### FR-13 Rule Schema 3.0 离线结构与确认事实目录

- 项目报告与原始数据规则使用独立规则集；V3 规则结构原生表达状态守卫、前置条件、有序 eligibility、
  后置门禁、排除条件、受控 outcome 和默认结果。
- `RuleStructureCandidateV3` 只包含规则结构、确认事实编码引用、原因、建议及显式阻断；不包含测试
  案例、规则版本、Parser 元数据、物理映射、发布或执行状态。
- `BusinessConfirmedFactCatalogV3` 以不可变 ID、版本、canonical digest、参数角色、值域、空值契约、
  binding profile 引用和证据约束模型自由度。
- binding profile 尚未提供时，逻辑事实保留确认来源而 bindingProfileRef 为空并附 bindingIssues，
  不合成批准引用。目录元数据不由规则结构候选输出。
- 第 1.3 节以外的附件内容不进入规则块；7 个视图仅作实现证据，SQL 不执行也不进入候选。
- 缺少确认事实时使用 blocked 节点、`blockingIssues` 和 `proposedFacts`，不得伪造 confirmed 条件。
- Slice 1/2 只提供离线领域能力与静态 Schema；运行时默认、V1/V2 历史对象、MongoDB 和现有交接均不变。
- 后续单独授权的 REPORT_RELEASE / ruleStructure 显式命令允许 1 至 3 次共享预算的内存纠错；
  默认仍为 1 次，业务确认缺口优先停止，失败候选不落盘，且不切换 V2 默认入口。

## 5. 非功能要求

- 安全失败：模型超时、限流、空响应、非法 JSON 或校验失败时，不产生有效规则草稿。
- 可测试：默认测试不调用真实网络或模型，模型交互可被测试替身替换。
- 可互操作：事实绑定样例同时通过 Pydantic 和独立 Draft 2020-12 validator；Schema 生成物与领域模型差异必须由测试发现。
- 可复核：同一解析结果能够定位到准确的源文件内容和解析版本。
- 最小依赖：第一阶段只允许 MongoDB 连接、Schema migration、显式草稿版本归档、任务专属 REQ 授权的不可变事实交接，以及 [REQ-20260827-02](REQ-20260827-02-deepseek-retry-audit-idempotency.md) 授权的有界进程内幂等缓存；不引入外部/共享缓存、消息队列、向量库或 Wiki SDK。
- 数据安全：配置、日志和测试夹具不得包含密钥或未脱敏业务数据。
- 技术约束：应用与测试使用 Python `3.11.9`，Agent 工作流使用 LangGraph，模型供应商使用 DeepSeek；领域规则与确定性校验保持框架和供应商无关。

## 6. 第一阶段非目标

第一阶段不包含在 RuleReader 内实现 Agent 2、Wiki/RAG、SQL、数据库元数据发现、事实注册、规则执行、审批发布、草稿覆盖更新、删除回滚、决策追踪、销售查询、生产集成和 UI。只增加 [REQ-20260818-04](REQ-20260818-04-rule-version-persistence.md) 的不可变草稿归档、[REQ-20260819-01](REQ-20260819-01-rule-contract-v2-agent2-handoff.md) 的事实请求导出和 [REQ-20260824-01](REQ-20260824-01-mongodb-fact-binding-handoff.md) 的不可变 MongoDB 交接，不建设正式规则生命周期。

## 7. 第一阶段产品验收

- FastAPI 服务可启动，配置可脱敏读取，MongoDB 可从空库幂等初始化。
- 代表性 Markdown 规则可以转换为符合 Schema 的待审核草稿。
- 正常、反向、边界、嵌套、例外、缺失字段、歧义和非法输出均有可重复验证的结果。
- `requiredFacts`、条件引用、测试案例和来源信息通过确定性校验。
- 复杂公式和分支保存在 Schema `2.0.0` AST 中，案例实际执行结果与期望一致。
- 非派生事实可导出 Agent 2 请求，Schema `1.0.0` 请求明确失败。
- `FactBindingRequest 2.0.0` 的正向未决样例通过独立 Schema，漏必填字段、未知字段、错误契约版本和旧版载荷明确失败；HTTP 默认与显式输出均固定为 `2.0.0`。
- 用户可显式保存校验通过的草稿，并按版本号回读完全一致的业务 JSON。
- 用户可从已持久化 V2 规则幂等保存不可变事实交接；哈希冲突、旧 Schema 和非持久化来源明确失败，且历史规则记录不被修改。
- 业务审核阻断修订必须形成不同 `ruleVersion` 的待审核草稿；离线校验和导出不等于持久化、业务批准、发布或可执行状态。
- DeepSeek 可重试调用按有界退避执行并逐次审计；同一进程内同键同请求不重复调用 Provider，同键异请求明确冲突，失败不长期缓存。
- 失败场景不会生成可被误认为正式规则的产物。
- 代码和依赖中不存在第一阶段明确排除的 Wiki 或后续模块实现。

详细技术验收在第一阶段 `DEV` 文档中冻结后执行。
