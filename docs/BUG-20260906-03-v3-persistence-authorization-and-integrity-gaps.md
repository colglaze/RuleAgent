# BUG-20260906-03：V3 持久化授权与完整性验收缺口

- 状态：`FIXED`（2026-09-06 第三轮复核后恢复）
- 日期：2026-09-06
- 来源需求：[REQ-20260906-01](REQ-20260906-01-v3-mongodb-persistence.md)
- 关联设计：[DEV-20260906-02](DEV-20260906-02-v3-mongodb-persistence.md)（含验收修订章节）
- 关联决策：[BIZ-20260906-02](BIZ-20260906-02-v3-mongodb-persistence.md)（含验收修订章节）

## 现象与影响（已确认复现）

1. **Schema v5 无条件升级**：`LATEST_SCHEMA_VERSION=5` 后，普通服务启动、`rule-reader init-db`、
   V1/V2 parse persistence、V2 handoff 与 V3 candidate recovery 都会经 `MongoManager.initialize()`
   应用全部 migration，把未授权的数据库升到 v5 并创建两个 V3 集合。
2. **持久化对象未绑定获批身份**：脚本只校验 manifest 内部一致性，任何 synthetic 2-request
   产物（自带自洽 manifest）都能通过 `load_and_validate_delivery`；而
   [BIZ-20260906-02](BIZ-20260906-02-v3-mongodb-persistence.md) 固定的持久化对象是
   `REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a` 与 18 条请求。
3. **畸形 request 泄漏裸异常**：requests 数组中的非法项抛出 Pydantic `ValidationError`，不是
   稳定的 `V3PersistenceError` 子类；CLI 会输出 traceback 与 `input_value` 原始内容。
4. **回读容忍乱序**：`_parse_stored_batch` 先排序再比较，存量 `requests` wrapper 顺序被反转时
   仍能回读成功，掩盖存储层损坏。
5. **回读容忍重复身份**：重复 request ID 的 wrapper（连同重算的 batch hash 与计数）仍能回读
   成功；factCode 重复同样不被拒绝。
6. **integration 断言过期**：两个 integration 测试仍以 Schema v4 为最终状态，缺少显式
   target v5 的迁移与 V3 集合/索引检查。
7. **pyvenv.cfg 漂移**：`command` 仍指向旧解释器位置 `D:\Python\python.exe`。
8. **进度文档陈述失实**：进度文档遗留问题声称 `.obsidian/workspace.json` 当前有未提交修改；
   该文件本身与已提交状态无差异（复核更正：见下文“复核发现”第 5 条，工作区整体存在大量
   未提交/未跟踪内容，不得写“工作区 diff 为空”）。

## 修复

1. migration 增加显式 `target_version`：`RUNTIME_SCHEMA_VERSION=4`、
   `V3_PERSISTENCE_SCHEMA_VERSION=5`、`LATEST_SCHEMA_VERSION=5`；普通 serve/init-db/V1-V2/V3
   恢复默认只到 v4；仅 V3 持久化脚本在全部离线校验通过后显式请求 v5；v5 库上普通应用正常启动，
   不降级、不重写；非法或超出支持的 target 在任何写入前失败。见 REQ/DEV 验收修订章节。
2. 脚本先以固定常量校验 manifest 文件自身 SHA-256（`0ef3af69...`），再信任其内容并校验五个
   交付文件哈希与固定 ruleVersion、requestCount=18、testCaseCount=20、ready=true、blocking=0、
   executable=false；不提供任何绕过参数或环境开关。
3. 逐项 request 解析错误转换为 `V3PersistenceContractError`；`MongoStartupError` 转换为
   `V3PersistenceUnavailableError`；`main` 捕获预期错误，向 stderr 输出最小 JSON
   （code/message/retryable/details=[]）并以非零码退出，无 traceback、无 URI/路径/payload。
4. `_parse_stored_batch` 在排序前校验存储顺序：wrapper 顺序严格升序、`request_ids` 与存储顺序
   逐项一致、request ID/factCode 无重复、wrapper `created_at` 为 aware UTC 且等于 batch
   `created_at`；rule `stored_at` 同样要求 aware UTC，不再静默补时区。
5. integration 测试更新为 v4 常规 + 显式 v5 目标两段（本轮不运行）。
6. `.venv/pyvenv.cfg` 的 `command` 修正为当前解释器位置；进度文档删除失实陈述，manifest 校验
   描述改为“可信 manifest 自身 SHA-256 + manifest 内记录的五个交付文件 SHA-256”。
7. `delivery_summary`：rule 或 batch 任一本次新插入即不得报告 `existingAndVerified`；新增
   “规则已存在、batch 本次补写”的恢复状态 `recoveredAndVerified`。

## 验收证据

见 `docs/PROG-20260906.md` 本轮记录：新增失败测试先复现后转绿，默认套件、Ruff、严格 Mypy、
`pip check`、`git diff --check` 与 Markdown 链接检查全部通过；integration 测试未运行（未授权
真实数据库）；真实 MongoDB 未访问、未写入。

## 复核发现（2026-09-06 第三轮，状态重开）

独立复核确认以下问题，本轮只修复、不访问真实 MongoDB、不运行 integration 或持久化脚本：

1. **Settings 构造在错误转换之外**：`scripts/persist_report_release_v3_delivery.py` 的
   `_persist_via_mongodb` 中 `Settings()` 位于 `MongoStartupError/V3PersistenceError` 转换之外。
   配置非法（如环境变量格式错误）时 CLI 抛出 Pydantic `ValidationError`/traceback，违反本缺陷
   第 3 条的脱敏要求。
2. **integration 测试语义错误**：`tests/integration/test_mongodb.py` 把 wrappers 乱序的
   `PreparedV3HandoffBatch` 直接交给 repository 并期待幂等（`inserted=False`）；实际实现按
   设计返回 `V3PersistenceConflictError`。输入顺序无关性属于应用服务（`prepare_v3_delivery`
   统一排序）语义，非法 prepared record 必须由仓储拒绝，不得被描述为幂等输入。
3. **验证基线更正**：当前真实验证是 `173 passed, 5 deselected` 与 **514** 个 Markdown 相对
   链接（前一轮记录的 512 为修复前旧值，记录过程有误）。
4. **Git 状态更正**：Git 已安装在 `D:\LeStoreDownload\Git\cmd\git.exe`。仓库因重装系统触发
   dubious ownership 保护；使用单次 `git -c safe.directory=D:/Python/pyWorkspace/RuleAgent ...`
   参数可执行只读检查，未修改全局 Git 配置。`git diff --check` 当前通过。
5. **工作区状态更正**：`git diff --check` 通过不等于工作区 clean——当前工作区存在大量未提交
   和未跟踪的 V3 工作文件；只有 `.obsidian/workspace.json` 单独无差异。不得声称“工作区 diff
   为空”或“工作区 clean”。
6. **.obsidian/workspace.json**：该文件本身与已提交状态无差异（`git diff -- <path>` 为空）。
7. **真实 MongoDB 访问史更正**：此前“真实 MongoDB 从未被本仓库访问”的陈述错误。历史记录表明
   2026-09-05 已确认正式数据库为 Schema v4 且存在一条 V3 recovery 记录；本轮验收修订只是
   没有访问数据库，当前实时状态未重新确认。Schema v5 migration 与 V3 正式交付仍未执行。

## 第三轮复核修复证据（状态恢复 FIXED）

1. **Settings 配置错误脱敏**：新增失败测试
   `test_cli_reports_sanitized_error_for_invalid_settings`（修复前 `ValidationError` 裸穿并
   产生 traceback）；修复后 `Settings()` 构造失败转换为
   `V3PersistenceUnavailableError("V3 persistence configuration is invalid")`，CLI 输出最小
   JSON（code=`V3_PERSISTENCE_UNAVAILABLE`、retryable=true、details=[]）并以退出码 1 结束，
   不构造 `MongoManager`、不访问数据库、stderr 不含 URI/用户名/密码/`input_value`/绝对路径。
2. **integration 语义更正**：`tests/integration/test_mongodb.py` 不再把乱序
   `PreparedV3HandoffBatch` 当作幂等输入——仓储对其期待 `V3PersistenceConflictError`；新增
   `test_v3_persistence_service_replay_is_input_order_independent` 证明应用服务层乱序 requests
   经 `prepare_v3_delivery` 排序后幂等重放（第二次 rule/batch 均 `inserted=False`，回读与首次
   时间不变）。integration 覆盖保持显式 v4、显式 v5、两新集合三唯一索引、v1-v4 不变、
   首写/重放/冲突。
3. **文档证据更正**：基线数字更正为 173 passed, 5 deselected 与 514 个链接（复核前记录）；
   Git 证据统一为 `D:\LeStoreDownload\Git\cmd\git.exe` + 单次 `-c safe.directory` 只读检查；
   删除“工作区 diff 为空/从未访问 MongoDB”的错误陈述。
4. **本轮验证**：`pytest tests/unit/test_persist_report_release_v3_delivery.py` → 14 passed；
   三个直接相关文件 → 44 passed；默认套件 → **174 passed, 6 deselected**（新增 1 个 Settings
   测试；新增 3 个 integration 测试仅完成导入/收集，未运行）；Ruff check/format、严格 Mypy
   （61 个源文件）、`pip check` 通过；`git -c safe.directory=... diff --check` 通过，
   `git diff -- .obsidian/workspace.json` 为空，`git status --porcelain` 94 行（工作区不
   clean）；Markdown 相对链接 **518 个全部有效**。integration 未运行；真实 MongoDB 未访问、
   未写入；未提交或推送。
