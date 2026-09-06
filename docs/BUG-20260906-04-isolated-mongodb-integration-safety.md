# BUG-20260906-04：隔离 MongoDB integration 测试安全门禁缺失

- 状态：`FIXED`（拓扑复核修复完成；integration 执行状态为
  `AWAITING_ISOLATED_MONGODB_CONFIGURATION`）
- 日期：2026-09-06
- 来源需求：[REQ-20260906-01](REQ-20260906-01-v3-mongodb-persistence.md)
- 关联设计：[DEV-20260906-02](DEV-20260906-02-v3-mongodb-persistence.md)
- 前序缺陷：[BUG-20260906-03](BUG-20260906-03-v3-persistence-authorization-and-integrity-gaps.md)

## 现象与影响（已确认）

1. **测试连接可回退到环境数据库**：`tests/integration/test_mongodb.py` 与
   `test_fact_binding_handoffs_mongodb.py` 使用
   `os.getenv("RULEREADER_TEST_MONGODB_URI") or Settings().mongodb_uri` 获取连接。当
   `RULEREADER_TEST_MONGODB_URI` 缺失时（当前正是如此），integration 测试会静默回退到
   `Settings().mongodb_uri`，即可能误连当前环境配置的业务数据库并对其执行 migration 与写入。
2. **migration 中途失败不清理随机测试库**：`database_created` 在首次 migration 成功后才置
   true；若 migration、索引创建或首次写入在中途失败，`finally` 不会删除该随机
   `rule_reader_test_<uuid>` 测试库，留下残留对象。

## 修复

1. 在 `tests/integration/mongodb_test_guard.py` 新增纯测试侧安全门禁（不进入 `src`，不成为
   生产依赖）：只从 `os.environ` 读取 `RULEREADER_TEST_MONGODB_URI` 与
   `RULEREADER_TEST_MONGODB_ALLOW_WRITE`；URI 缺失明确失败、禁止回退 Settings 或 `.env`；
   写入确认值必须精确等于 `isolated-local-only`；拒绝 `mongodb+srv`；用 PyMongo 既有 URI
   解析解析主机，所有节点必须是 `localhost`、`127.0.0.1` 或 `::1`；拒绝远程 IP/域名、空
   host 与无法解析的 URI；错误消息不包含完整 URI、用户名、密码或环境变量值；门禁通过后才
   把 URI 提供给 integration 测试；门禁为显式参数可离线测试的纯函数，导入时不连接数据库，
   不提供命令行/Settings/默认值绕过。
2. 两个 integration 测试删除 `Settings().mongodb_uri` 回退，统一调用门禁；`ping` 成功后、
   任何写入之前即武装清理标志，任何中途失败也会在 `finally` 删除该随机测试库；删除前再次
   断言库名以 `rule_reader_test_` 开头；不枚举、不批量删除、不使用用户配置的数据库名。
3. 新增离线单元测试 `tests/unit/test_mongodb_integration_guard.py` 覆盖缺失/错误 sentinel/
   srv/远程主机/多节点/非法 URI/三类回环主机/含认证回环 URI 等场景；默认 pytest 可运行且
   不建立网络连接。
4. 顺带修复 `test_persist_report_release_v3_delivery.py` 中对 `capsys.readouterr()` 的二次
   读取断言（第二次读取恒为空，脱敏断言无实效），改为对首次捕获内容断言。

## 验收证据

见 `docs/PROG-20260906.md` 本轮记录。实际验证（2026-09-06 第四轮）：

- 门禁离线测试 `tests/unit/test_mongodb_integration_guard.py` → **14 passed**（缺失/错误
  sentinel/srv/远程主机/多节点/非法 URI 脱敏/localhost/127.0.0.1/::1/含认证回环 URI 与凭据
  不回显）；
- 脚本专项 `tests/unit/test_persist_report_release_v3_delivery.py` → **14 passed**（含修复
  后对首次捕获 stderr 的真实脱敏断言）；
- 三个 Schema v5 相关测试文件 → **44 passed**；
- 默认套件 → **189 passed, 6 deselected**（新增 14 个门禁测试；5 个 integration 用例仅完成
  导入/收集，未运行）；
- Ruff check/format、严格 Mypy（61 个源文件）、`pip check` 通过；
- `git -c safe.directory=D:/Python/pyWorkspace/RuleAgent diff --check` 通过；
  `git diff -- .obsidian/workspace.json` 为空；`git status --porcelain` 97 行（工作区存在
  大量未提交/未跟踪内容，不 clean）；
- Markdown 相对链接检查 → **524 个全部有效**；
- **integration 未运行**：`RULEREADER_TEST_MONGODB_URI` 与
  `RULEREADER_TEST_MONGODB_ALLOW_WRITE` 当前均未配置；真实 MongoDB 未访问、未写入。

## 拓扑复核发现（2026-09-06 第五轮）

第四轮门禁只检查 URI nodelist 主机为 loopback，但仍接受以下 URI：

- `mongodb://localhost:27017/?replicaSet=prod`
- `mongodb://localhost:27017/?directConnection=false`
- `mongodb://localhost:27017/?loadBalanced=true`

这些选项可能允许驱动执行副本集拓扑发现、多节点路由或负载均衡，不能证明连接始终停留在
loopback 单节点。修复方向：URI query option 采用严格 allowlist（仅 `directConnection`、
`authSource`、`authMechanism`），且 `directConnection` 必须显式为 `true`；`replicaSet` 与
`loadBalanced` 无论取值为何都拒绝；其他任何 option 一律拒绝，避免未来新增的发现、代理或
路由能力绕过门禁。详见 [DEV-20260906-02](DEV-20260906-02-v3-mongodb-persistence.md) R7。

## 拓扑复核修复证据（2026-09-06 第五轮，状态恢复 FIXED）

1. **失败测试先行**：7 个拒绝类测试在收紧前失败（缺 directConnection、directConnection=
   false、replicaSet、loadBalanced、allowlist 外选项、replicaSet 名称不回显、凭据不回显）；
   3 个通过类测试（directConnection=true + localhost/127.0.0.1/[::1]）与含认证、authSource、
   directConnection=true 的回环 URI 通过类测试在收紧前后均保持通过。
2. **门禁收紧**：`ALLOWED_OPTIONS = {directconnection, authsource, authmechanism}` 严格
   allowlist（键名小写比较，大小写不敏感 option 名统一覆盖）；allowlist 外已知 option 拒绝
   并只回显 option 名（不回显值）；pymongo 未知 option 由 parse 层拒绝并经脱敏边界转换为
   固定错误；`replicaSet`/`loadBalanced` 显式拒绝；`directConnection` 必须显式 `true`。
3. **验证**：门禁离线测试 → **25 passed**（无网络连接）；默认套件 → **201 passed,
   6 deselected**（5 个 integration 用例仅导入/收集）；Ruff check/format（179 files already
   formatted）、严格 Mypy（61 个源文件）、`pip check` 通过；`git diff --check` 通过、
   `.obsidian/workspace.json` 无差异；Markdown 相对链接 **527 个全部有效**。
4. **integration 未运行**：`RULEREADER_TEST_MONGODB_URI` 与
   `RULEREADER_TEST_MONGODB_ALLOW_WRITE` 经只读存在性检查确认均未配置（未输出任何值），
   门禁前置条件不满足，不连接、不 ping；当前执行状态
   `AWAITING_ISOLATED_MONGODB_CONFIGURATION`。真实 MongoDB 未访问、未写入。
5. 5 个 integration 用例的清理逻辑经复核继续满足：随机库名由测试代码生成、ping 后写入前
   武装清理、finally 删除前再次断言前缀、仅 `drop_database(精确名)`、中途失败也清理、不
   打印 URI/凭据。
