# BUG-20260906-01：换机后 Python 环境与 V3 交付记录漂移

- 状态：`FIXED`
- 日期：2026-09-06
- 来源需求：[REQ-20260905-02](REQ-20260905-02-v3-agent2-handoff-readiness.md)
- 关联设计：[DEV-20260906-01](DEV-20260906-01-rule-parse-result-v3.md)

## 现象与影响

1. 系统重装后，裸 `python`/`python3` 命令只命中 Windows Store alias；实际已安装的
   Python `3.11.9` 位于 `D:\Python\python.exe`。
2. 仓库原 `.venv` 的 `pyvenv.cfg` 仍指向旧 Windows 用户目录下的解释器，因此项目命令无法运行。
3. Slice 3-6 已离线完成，但 README、PRD、技术设计、实施文档和部分任务文档仍显示 16 项
   blocking 或 Slice 1/2 状态；进度文档记录的 requests 与 manifest SHA-256 也无法由固定命令复现。

这会让新环境误判为“未安装 Python”，并让接手者误判当前 V3 是否已经形成 Agent 2 就绪交付物。

## 原因

- `.venv` 不可跨系统安装或 Windows 用户目录搬迁复用；其解释器路径保留了旧环境的绝对地址。
- Slice 3-6 完成状态未同步到所有顶层权威文档；两项哈希记录与当前固定输入、固定
  `generatedAt` 下的确定性产物不一致。

## 修复

- 通过 Python 注册表安装信息定位并验证 `D:\Python\python.exe` 为 Python `3.11.9`。
- 使用该解释器原位重建 `.venv`，安装 `requirements-dev.lock` 与本项目 editable package。
- 使用固定 `generatedAt=2026-09-05T17:24:07+00:00` 重新生成 V3 confirmed 离线产物，确认
  catalog、candidate、result 与 readiness 哈希保持不变，并以实际可复现值更正文档中的 requests
  与 manifest 哈希。
- 同步 README、PRD、技术设计、实施文档、REQ、DEV、BUG 与进度记录中的当前状态；历史阻断
  结论保留为阶段性记录，不改写为当时已就绪。

本修复未访问或修改 MongoDB，未调用 DeepSeek、SQL Server 或 SqlBot，也未生成或执行 SQL。

## 验收证据

- `D:\Python\python.exe --version`：`Python 3.11.9`。
- `.\.venv\Scripts\python.exe --version`：`Python 3.11.9`。
- `.\.venv\Scripts\python.exe -m pytest`：`128 passed, 3 deselected`。
- `ruff check .`：通过；`ruff format --check .`：161 个文件已格式化。
- `mypy`：56 个源文件通过；`pip check`：无损坏依赖。
- 固定离线再生产物：18 条 `FactBindingRequest 3.0.0`，readiness `16/16` 全通过，
  `ready=true`；requests SHA-256 为
  `dfca3a6d6bb4333f5905f7e5ae4269f599265f5e520a8d252edf2b1f82342dad`，manifest SHA-256 为
  `0ef3af6939d7cdf9b206bd97d709c58f2308f87af625e082f88b03e35d20b0c4`。

## 非阻断环境遗留

- 当前终端尚未把 `D:\Python` 持久化到用户 PATH；项目已可通过 `.venv` 正常运行，不影响本仓库。
- 当前机器未发现可执行的 Git，故本次无法提供 `git status`/`git diff --check` 证据，也没有提交或推送。
