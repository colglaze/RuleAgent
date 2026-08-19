# BUG-20260818-01：`.env` 被错误取消忽略

- 状态：`FIXED`
- 日期：2026-08-18
- 来源 REQ：[REQ-20260818-02](REQ-20260818-02-backend-skeleton.md)
- 发现于：[REQ-20260818-04](REQ-20260818-04-rule-version-persistence.md) 收口检查

## 现象

`.gitignore` 先忽略 `.env`，随后却使用 `!.env` 将其重新放行；这与项目“不得提交密钥”的约束冲突，而 `.env.example` 反而会被 `.env.*` 忽略。

## 修复

把例外规则改为 `!.env.example`。真实 `.env` 继续被忽略，安全模板可以纳入版本管理。

## 验证

静态检查忽略规则只出现 `.env`、`.env.*` 和 `!.env.example`，高置信度密钥扫描排除未跟踪 `.env` 后无命中。
