# BIZ-20260818-04：FastAPI 后端与 MongoDB 基础设施

- 状态：`ACCEPTED`
- 日期：2026-08-18
- 来源 REQ：[REQ-20260818-02](REQ-20260818-02-backend-skeleton.md)
- 影响范围：工程骨架、服务入口、配置、数据库初始化和实施顺序

## 1. 决策

1. 后端 HTTP 服务使用 FastAPI，进程由 Uvicorn 启动。
2. 配置使用 Pydantic Settings 统一加载，环境变量前缀为 `RULEREADER_`，本地可使用未跟踪的 `.env`。
3. MongoDB 使用 PyMongo Async API；不采用 Motor。
4. 依赖管理采用 Python 标准 `venv + pip + pyproject.toml`，直接依赖精确固定，并生成 pip freeze 锁文件。
5. MongoDB 默认 URI 为 `mongodb://localhost:27017/`，默认数据库名为 `rule_reader`。
6. 服务启动采用 fail-fast：连接、ping 或初始化失败时，不接受请求。
7. 数据库初始化采用版本化、幂等迁移；本任务只创建基础设施集合 `schema_migrations` 与 `app_metadata`。
8. DeepSeek 配置可读取但保持可选，本任务不调用模型。

## 2. 与既有范围的关系

本决策根据用户最新要求，部分覆盖 [REQ-20260818-01](REQ-20260818-01-vibe-coding-bootstrap.md) 中“第一阶段不引入 MongoDB”的限制。允许范围仅为服务连接、健康检查和基础设施 Schema 初始化；正式规则版本库、规则持久化和业务执行仍然禁止提前实现。

后端骨架作为 Phase 1.0，先于 Rule Parsing Agent 的契约与实现切片完成。

## 3. 取舍

- FastAPI 只负责交付和生命周期边界，不承载领域规则逻辑。
- PyMongo Async API 与 FastAPI 的异步生命周期一致，并避免采用已进入迁移周期的 Motor。
- 不引入额外包管理器，降低本机启动门槛；锁文件确保环境可复现。
- 不用 HTTP URL 访问 MongoDB，驱动 URI 必须使用 MongoDB scheme。
- 不把密钥或完整数据库 URI 暴露到健康检查、配置 API 或日志。

## 4. 变更规则

更换 Web 框架、MongoDB 驱动、配置前缀、初始化策略或数据库名默认值，必须先更新本 BIZ/DEV 并提供迁移与回归证据。

## 5. 官方依据

- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
- [PyMongo Async migration](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/)
- [MongoDB client URI](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/mongoclient/)
- [Pydantic Settings](https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/)
