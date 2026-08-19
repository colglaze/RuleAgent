# REQ-20260818-02：后端服务骨架与 MongoDB 初始化

- 状态：`DONE`
- 日期：2026-08-18
- 来源：用户本次明确要求
- 前置需求：[REQ-20260818-01](REQ-20260818-01-vibe-coding-bootstrap.md)
- 实施决策：[BIZ-20260818-04：FastAPI 后端与 MongoDB 基础设施](BIZ-20260818-04-backend-fastapi-mongodb.md)
- 技术方案：[DEV-20260818-01：后端骨架](DEV-20260818-01-backend-skeleton.md)

## 1. 背景

RuleReader 已确定 Python `3.11.9`、LangGraph 和 DeepSeek，但仓库尚无可运行工程。用户要求先建立后端骨架，使服务可启动、配置可读取，并连接已运行在 Docker 中的 MongoDB 完成幂等初始化。

用户提供的 `http://localhost:27017/` 表示本机 27017 端口；MongoDB 驱动连接必须使用 `mongodb://localhost:27017/`。本机检查已确认容器 `mongodb` 运行且端口可达。

## 2. 范围内

- 建立锁定 Python `3.11.9` 的 `src/` 布局 Python 工程。
- 使用 FastAPI 提供 HTTP 服务，使用 Uvicorn 启动。
- 使用 Pydantic Settings 从环境变量和本地 `.env` 统一读取、校验配置。
- 提供脱敏配置检查命令和只返回非敏感信息的配置端点。
- 使用 PyMongo Async API 连接 MongoDB，并在应用 lifespan 中管理连接。
- 启动时执行 MongoDB ping 和幂等 Schema 初始化；初始化失败时服务启动失败。
- 建立 `schema_migrations` 与 `app_metadata` 基础设施集合及必要索引，不创建正式规则业务集合。
- 提供存活与就绪健康检查、配置样例、测试和启动说明。

## 3. 范围外

- Rule Parsing Agent、LangGraph graph、DeepSeek 实际调用和 Prompt。
- 正式规则存储、规则发布、事实注册、规则执行和诊断数据。
- Wiki、Agent 2、SQL、认证授权、前端、部署与 Docker Compose。
- 自动创建、启动、重启或修改用户的 MongoDB Docker 容器。

## 4. 验收标准

- `python --version` 为 `3.11.9`，项目元数据拒绝其他 Python 版本。
- 配置检查命令可读取默认值或 `.env`，且不输出 MongoDB URI、密码或 DeepSeek Key。
- MongoDB URI 使用 `mongodb://` 或 `mongodb+srv://`；传入 `http://` 时配置校验明确失败。
- 初始化命令能从空数据库创建 Schema v1，重复运行不报错、不产生重复迁移。
- FastAPI 服务启动后，`/health/live` 返回 200，MongoDB 可用时 `/health/ready` 返回 200。
- `/api/v1/config` 只返回可公开配置和“是否已配置”状态。
- 默认单元测试不依赖真实 MongoDB；显式 integration 测试验证空库初始化和重复升级。
- Ruff、Mypy、单元测试、integration 测试与实际服务启动检查通过。

## 5. 用户待填写配置

本机 `mongodb` 容器已启用认证，不能使用匿名默认 URI 完成初始化。用户需要复制根目录 `.env.example` 为 `.env`，并填写带用户名、URL 编码密码和 `authSource=admin` 的 `RULEREADER_MONGODB_URI`；凭据不得提交。数据库名默认使用 `rule_reader`。

DeepSeek 尚未在本任务中调用，因此 `RULEREADER_DEEPSEEK_API_KEY`、`RULEREADER_DEEPSEEK_BASE_URL` 和 `RULEREADER_DEEPSEEK_MODEL` 可以先留空。
