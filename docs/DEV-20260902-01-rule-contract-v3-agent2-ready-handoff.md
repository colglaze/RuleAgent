# DEV-20260902-01：Rule Schema 3.0 Slice 1/2 实现

- 状态：`IMPLEMENTED_RECONSTRUCTED`
- 日期：2026-09-02
- 来源需求：[REQ-20260902-01](REQ-20260902-01-rule-contract-v3-agent2-ready-handoff.md)
- 业务决策：[BIZ-20260902-01](BIZ-20260902-01-rule-v3-agent2-ready-boundary.md)

## 契约

- `catalog_v3.py` 定义确认事实、证据、参数角色和目录；digest 使用 UTF-8、排序键、紧凑 JSON，计算时
  排除自引用的 `catalogDigest`。
- `v3.py` 定义规则候选、五阶段、active/blocked 规则、受控 outcome、阻断和 proposed fact。
- 条件和表达式复用已冻结的 V2 结构节点，但 V3 候选不加入 `RuleDocument` 联合类型。
- 两个根模型采用 camelCase、`extra=forbid` 和 Draft 2020-12 `$id`。

## 确定性门禁

`validation_v3.py` 依次校验目录、候选安全文本、目录身份、阶段顺序、全局唯一编码、priority、
blocking 引用、确认事实闭包、proposed fact 冲突和表达式类型。独立的外部 witness 门禁证明每个
active rule 能成为所属阶段的首个命中项；witness 不写入候选契约。解释器先执行同一门禁，再按阶段
与 priority 求值；缺失输入、错误类型和值域外输入明确失败或返回 `INDETERMINATE`。

## 来源与模型边界

`source_v3.py` 只在调用方提供的文本内提取唯一命名规则块并计算 SHA-256；不读 Office、不扫描目录。
`workflow_v3.py` 使用独立 LangGraph 分支，保存单次运行内的 previous candidate、feedback、调用次数和
provider-neutral audit。最多 3 次；业务确认缺口不可重试，候选不落盘。

换机恢复增加固定私有 bundle 校验器：按 manifest SHA-256 定位设计来源与字段工作簿，再以精确起止
标记提取有序 REPORT_RELEASE 块。校验器只输出 bundle、workbook 和 rule block 身份，不回显规则、
字段或 SQL。真实 profile 从工作簿固定坐标读取用户确认值；读取器不执行公式和宏。

公开脚本只接受显式外部文件：`validate_rule_structure_v3.py` 完成离线校验；
`run_report_release_agent1_v3_once.py` 必须带 `--allow-provider` 且固定单次请求。README 不提供私有
bundle 路径假设。

## 测试

合成目录与候选覆盖 digest 篡改、重复 ruleCode、目录外事实、blocked 形状、阻断解释、状态守卫、
后置降级、缺失输入、可达性 witness、唯一规则块、有界纠错、业务缺口早停、请求硬上限和 DeepSeek
显式 prompt/payload。
契约导出测试在临时目录重建全部公开 JSON 并与受管文件比较。
