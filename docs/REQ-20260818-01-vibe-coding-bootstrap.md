# REQ-20260818-01：Vibe Coding 基线与 Rule Parsing Agent 第一阶段

- 状态：`ACCEPTED`
- 日期：2026-08-18
- 来源：用户本次明确要求
- 关联决策：[BIZ-20260818-01：第一阶段使用本地文档](BIZ-20260818-01-phase1-local-documents.md)
- 技术栈决策：[BIZ-20260818-02：使用 Python 与 LangGraph](BIZ-20260818-02-python-langgraph.md)
- 运行时与模型决策：[BIZ-20260818-03：Python 3.11.9 与 DeepSeek](BIZ-20260818-03-python311-deepseek.md)
- 长期方案：[项目释放规则治理与诊断系统最终方案](../project_release_double_agent_solution.md)

## 1. 背景

仓库已有长期总体方案和空白的项目文档骨架，但缺少能约束后续 Coding Agent 的项目级工作约定，也没有把当前第一阶段与长期目标区分开。若直接按长期方案编码，容易一次性铺开 Wiki、两个 Agent、规则引擎、数据库和诊断链路，超出当前验证目标。

## 2. 本次目标

- 建立可持续的 Vibe Coding 文档与行为基线。
- 编写项目专属 `AGENTS.md`，让后续 Agent 能自主找到权威上下文、遵守范围门禁并提供完成证据。
- 冻结第一阶段为 Rule Parsing Agent 的最小闭环，规则输入先使用本地 Markdown 文档。
- 保留根目录总体方案作为长期目标，不把其全部模块视为第一阶段交付物。

## 3. 第一阶段能力范围

### 3.1 范围内

- 从受控目录读取本地 Markdown 规则文档。
- 解析规则编号、适用范围、条件、例外、失败说明、处理建议和责任角色。
- 生成待审核的结构化规则 JSON 草稿。
- 提取 `requiredFacts`，并生成或保留正向、反向和边界测试案例。
- 对输出执行 JSON Schema 和确定性语义校验。
- 保存可追溯的来源信息，并对解析失败返回明确错误。

### 3.2 范围外

- Wiki API、Wiki 同步、RAG、向量检索和知识库问答。
- Agent 2、数据库元数据分析、SQL 生成、SQL 审核与执行。
- 正式规则发布、MongoDB、事实注册中心、规则执行引擎和决策原因树。
- 销售查询 Agent、业务诊断链路、生产系统集成和 UI。

## 4. 本次文档交付验收标准

- `AGENTS.md` 明确权威文档顺序、当前阶段边界、文档治理、实现约束、测试要求和 DoD。
- `docs/PRD.md`、`docs/技术设计文档.md`、`docs/实施文档.md`、`docs/进度文档.md` 不再为空，并共同指向同一阶段边界。
- 阶段收窄决策有独立 `BIZ` 记录，且 `PROG` 可追溯到本 REQ。
- 根目录长期方案明确说明其定位，并与当前阶段计划不存在冲突。
- 技术设计和总体方案统一采用 Python `3.11.9`、LangGraph 与 DeepSeek，不残留 Java/Spring AI 实施指引。
- 本次不创建应用代码、模型接入、Wiki 占位实现或未来模块骨架。

## 5. 后续验收原则

第一阶段实现的详细输入 Schema、输出 Schema、DeepSeek 模型 ID 与调用方式、应用入口和样例集合应在编码前通过独立 `DEV` 文档冻结。任何扩大第一阶段范围的决定都必须先更新本 REQ 或创建新的 REQ/BIZ。
