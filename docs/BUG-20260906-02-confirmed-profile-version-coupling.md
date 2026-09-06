# BUG-20260906-02：confirmed profile parserVersion 与应用包版本耦合

- 状态：`FIXED`
- 日期：2026-09-06
- 来源需求：[REQ-20260905-02](REQ-20260905-02-v3-agent2-handoff-readiness.md)
- 关联需求：[REQ-20260906-01](REQ-20260906-01-v3-mongodb-persistence.md)
- 关联设计：[DEV-20260906-02](DEV-20260906-02-v3-mongodb-persistence.md)

## 现象与影响

`scripts/report_release_v3_confirmed_profile.py` 的 `_build_result` 从
`rule_reader.core.version.__version__` 读取 parserVersion。应用版本升级到 `0.12.0` 后，对固定
source、catalog、generatedAt 对应的同一 `ruleVersion` 重新生成 confirmed profile 会产生不同的
`parserVersion`、不同的 result payload 与不同的 canonical hash。

这会破坏既有不可变产物的可复现性：同一 ruleVersion 将对应两个不同的 payload/hash，任何依赖
固定产物身份的持久化、审计或比对都会失败，且数据库中可能留下“同 identity 异 hash”的冲突记录。

## 原因

parserVersion 是解析器/导入器 provenance，语义上应绑定“生成该 profile 的那次不可变导入”，而
`__version__` 是应用包发布版本，二者生命周期不同。脚本错误地用应用包版本充当 provenance 常量。

## 修复

- 脚本新增常量 `CONFIRMED_PROFILE_PARSER_VERSION = "0.11.0"`（既有 confirmed 产物使用的值），
  `_build_result` 的 `source.parserVersion` 与 `parser.parserVersion` 固定使用该常量，不再读取
  `__version__`；
- 新增回归测试：confirmed profile 的 parser provenance 固定为该常量且不随应用包版本变化
  （升级到 `0.12.0` 后 parserVersion 仍为 `0.11.0`）；
- 不修改既有 confirmed 产物内容与身份。

## 验收证据

- 既有产物 SHA-256 保持不变：catalog
  `2fbb7a0541a0f4e070855070c481c8851ac1a274ebc61024d268b80cc62fb87a`、candidate
  `a114d59f7432224715b3e9877a14d62fe7e28961484c66b6eebae3222c48ed58`、result
  `16fafc47077e297617d91b4fd115d078b3949e13487b03b97b7ba09949b0e432`、requests
  `dfca3a6d6bb4333f5905f7e5ae4269f599265f5e520a8d252edf2b1f82342dad`、readiness
  `67e5ae2338183fe8449316cffde250a7d8fa5f1960aa879e081a421d7893bfc4`、manifest
  `0ef3af6939d7cdf9b206bd97d709c58f2308f87af625e082f88b03e35d20b0c4`；
- 应用版本升级到 `0.12.0` 后，以固定输入与固定 `generatedAt` 向临时目录再生 confirmed 产物，
  六个文件哈希与既有产物逐字节一致（再生目录使用后删除，未覆盖任何既有产物）；
- 回归测试证明 `_build_result` 的 parserVersion 与 `rule_reader.core.version.__version__` 解耦。
