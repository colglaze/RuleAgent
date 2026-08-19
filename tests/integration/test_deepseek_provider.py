from __future__ import annotations

import pytest

from rule_reader.application.rule_parsing.workflow import RuleParsingService
from rule_reader.core.config import Settings
from rule_reader.infrastructure.deepseek import DeepSeekChatModel


@pytest.mark.provider_integration
@pytest.mark.asyncio
async def test_real_deepseek_returns_a_valid_rule_draft() -> None:
    settings = Settings()
    if not all(
        (
            settings.deepseek_api_key,
            settings.deepseek_base_url,
            settings.deepseek_model,
        )
    ):
        pytest.skip("DeepSeek is not configured")

    service = RuleParsingService(
        DeepSeekChatModel(settings),
        max_characters=settings.rule_max_characters,
        max_retries=settings.deepseek_max_retries,
    )
    text = """# 规则编号
TEST_PROVIDER_001
# 适用范围
正式实验任务测试释放。
# 生效条件
任务费用 `zssyjsfy` 大于等于 0，且任务状态为 19。
# 例外情况
特殊申请通过时转人工审核。
# 未通过原因
任务状态或费用不满足。
# 处理建议
核对任务状态和费用。
# 责任角色
项目负责人。
# 测试案例
- 状态 19、费用 100：通过
- 状态 18、费用 100：不通过
字段 `zssyjsfy` 来自 `v_OrderFormaltestsettlement`。"""

    await service.start()
    try:
        result = await service.parse_text(text, source_name="provider-test.md")
    finally:
        await service.close()

    assert result.rule.rule_id == "TEST_PROVIDER_001"
    assert result.status == "draft"
    assert result.executable is False
