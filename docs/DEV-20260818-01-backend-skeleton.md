# DEV-20260818-01：后端骨架

- 状态：`IMPLEMENTED`
- 日期：2026-08-18
- 来源 REQ：[REQ-20260818-02](REQ-20260818-02-backend-skeleton.md)
- 关联 BIZ：[BIZ-20260818-04](BIZ-20260818-04-backend-fastapi-mongodb.md)

## 1. 技术基线

| 类别 | 选择 |
| --- | --- |
| Python | `3.11.9` |
| 打包与安装 | `venv + pip + pyproject.toml` |
| HTTP | FastAPI `0.141.1` + Uvicorn `0.52.3` |
| 配置 | Pydantic Settings `2.15.0` |
| MongoDB | PyMongo Async API `4.17.0` |
| Agent 框架 | LangGraph `1.2.11`，本任务只固定依赖，不创建 graph |
| 测试 | Pytest `9.1.1`、pytest-asyncio `1.4.0`、HTTPX `0.28.1` |
| 静态检查 | Ruff `0.16.3`、Mypy `2.3.1` |

版本来自 2026-08-18 的包注册表查询，并在本机 Python `3.11.9` 环境实际安装验证。

## 2. 目录结构

```text
src/rule_reader/
  api/              HTTP 路由与依赖
  core/             配置、版本与日志
  infrastructure/   MongoDB 连接和迁移
  cli.py            serve/check-config/init-db
  main.py           FastAPI app factory
tests/
  unit/             无网络、无真实数据库
  integration/      显式连接 MongoDB
```

不创建 Rule Parsing、LangGraph graph 或 DeepSeek adapter 占位模块。

## 3. 配置契约

配置统一使用 `RULEREADER_` 前缀：

| 配置 | 默认值 | 是否必填 | 说明 |
| --- | --- | --- | --- |
| `RULEREADER_APP_NAME` | `RuleReader` | 否 | 服务名 |
| `RULEREADER_ENVIRONMENT` | `development` | 否 | `development/test/production` |
| `RULEREADER_HOST` | `127.0.0.1` | 否 | Uvicorn 监听地址 |
| `RULEREADER_PORT` | `8000` | 否 | Uvicorn 端口 |
| `RULEREADER_LOG_LEVEL` | `INFO` | 否 | 日志级别 |
| `RULEREADER_RELOAD` | `false` | 否 | 开发热重载 |
| `RULEREADER_MONGODB_URI` | `mongodb://localhost:27017/` | 当前容器需覆盖 | 完整驱动 URI，可包含认证信息 |
| `RULEREADER_MONGODB_DATABASE` | `rule_reader` | 否 | 当前服务数据库 |
| `RULEREADER_MONGODB_SERVER_SELECTION_TIMEOUT_MS` | `5000` | 否 | Server selection 超时 |
| `RULEREADER_MONGODB_CONNECT_TIMEOUT_MS` | `5000` | 否 | 连接超时 |
| `RULEREADER_DEEPSEEK_API_KEY` | 空 | Agent 阶段必填 | 本任务不使用 |
| `RULEREADER_DEEPSEEK_BASE_URL` | 空 | Agent 阶段确认 | 本任务不假定 Endpoint |
| `RULEREADER_DEEPSEEK_MODEL` | 空 | Agent 阶段确认 | 本任务不假定模型 ID |

完整 URI 和 Key 只在内存中使用。公开配置摘要只能显示数据库名、超时、模型名和布尔配置状态。

## 4. 应用生命周期

```text
加载并校验配置
→ 校验 Python 3.11.9
→ 创建 AsyncMongoClient
→ ping MongoDB
→ 执行幂等 Schema migration
→ FastAPI 接受请求
→ shutdown 时关闭 AsyncMongoClient
```

任何启动步骤失败都应关闭已创建资源并让进程以非零状态退出。

## 5. 数据库初始化

Schema v1：

- 创建 `schema_migrations`，为 `version` 建立唯一索引。
- 创建 `app_metadata`，为 `key` 建立唯一索引。
- 写入 `key=database_schema` 的元数据文档。
- 成功后记录 migration `version=1`、名称和 UTC 时间。

迁移必须可从空库执行，也必须在已存在 v1 时安全重跑。若数据库版本高于当前代码支持版本，启动必须失败。

## 6. HTTP 与 CLI 契约

- `GET /`：服务名、版本和文档入口。
- `GET /health/live`：进程存活，不访问外部资源。
- `GET /health/ready`：实时 ping MongoDB，失败返回 503。
- `GET /api/v1/config`：返回脱敏配置摘要。
- `rule-reader check-config`：输出同一份脱敏摘要。
- `rule-reader init-db`：连接并初始化数据库后退出。
- `rule-reader serve`：启动 Uvicorn。

## 7. 测试方案

- 配置默认值、环境覆盖、非法 HTTP Mongo URI 和敏感字段脱敏。
- App lifespan 的 connect/init/close 调用顺序。
- live、ready 成功/失败和配置 API。
- integration 测试使用唯一 `rule_reader_test_<uuid>` 数据库，从空库运行两次迁移并验证集合/索引；仅删除该测试创建的数据库。
- 实际运行 `init-db` 和服务 HTTP smoke test，使用用户现有 `mongodb` 容器。

## 8. DoD

- `ruff check .` 通过。
- `mypy src` 通过。
- 默认单元测试通过。
- 显式 MongoDB integration 测试通过。
- `init-db` 连续执行两次成功。
- 服务启动且三个 HTTP 检查端点返回预期状态。
- `.env.example`、README、锁文件、进度和 PROG 已同步。
