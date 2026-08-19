from __future__ import annotations

from typing import Any

from rule_reader.domain.rules.errors import ParseIssue, RuleParsingError


def valid_candidate(*, rule_id: str = "TEST_RELEASE_001") -> dict[str, Any]:
    return {
        "ruleId": rule_id,
        "title": "测试释放规则",
        "scope": "适用于测试任务的释放判断。",
        "sourceViews": ["v_test_release", "v_OrderFormaltestsettlement"],
        "requiredFacts": [
            {
                "key": "task_status",
                "name": "任务状态",
                "dataType": "integer",
                "description": "当前正式实验任务状态",
                "nullable": False,
            },
            {
                "key": "settlement_fee",
                "name": "任务费用",
                "dataType": "money",
                "description": "正式实验任务最终采用费用",
                "nullable": False,
            },
        ],
        "rootCondition": {
            "id": "root",
            "kind": "all",
            "description": "全部条件均满足",
            "children": [
                {
                    "id": "task-finished",
                    "kind": "predicate",
                    "description": "任务状态为完成",
                    "factKey": "task_status",
                    "operator": "eq",
                    "value": 19,
                },
                {
                    "id": "fee-covered",
                    "kind": "formula",
                    "description": "任务费用非负",
                    "expression": "settlement_fee >= 0",
                    "factRefs": ["settlement_fee"],
                },
            ],
        },
        "exceptionNotes": ["特殊申请通过时由人工复核。"],
        "failureReasons": ["任务状态或费用条件不满足。"],
        "recommendations": ["核对任务状态和任务费用。"],
        "responsibleRoles": ["项目负责人"],
        "testCases": [
            {
                "id": "pass-case",
                "description": "任务完成且费用有效",
                "given": {"task_status": 19, "settlement_fee": 100},
                "expected": "pass",
                "rationale": "全部条件满足",
            },
            {
                "id": "fail-case",
                "description": "任务未完成",
                "given": {"task_status": 18, "settlement_fee": 100},
                "expected": "fail",
                "rationale": "任务状态条件失败",
            },
        ],
        "fieldMappings": [
            {
                "factKey": "task_status",
                "mappingStatus": "unresolved",
                "viewName": None,
                "viewField": None,
                "note": "四视图目录没有任务状态输出字段。",
            },
            {
                "factKey": "settlement_fee",
                "mappingStatus": "mapped",
                "viewName": "v_OrderFormaltestsettlement",
                "viewField": "zssyjsfy",
                "note": "使用最终采用费用字段。",
            },
        ],
        "warnings": ["本规则仅用于测试。"],
    }


class QueueModel:
    def __init__(self, responses: list[str | ParseIssue]) -> None:
        self._responses = responses
        self.calls = 0
        self.started = 0
        self.closed = 0
        self.feedback: list[tuple[str, ...]] = []

    @property
    def model_name(self) -> str:
        return "fake-deepseek"

    async def start(self) -> None:
        self.started += 1

    async def close(self) -> None:
        self.closed += 1

    async def generate_candidate(
        self,
        *,
        text: str,
        candidate_schema: dict[str, Any],
        field_catalog: dict[str, Any],
        feedback: tuple[str, ...],
    ) -> str:
        del text, candidate_schema, field_catalog
        self.feedback.append(feedback)
        item = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        if isinstance(item, ParseIssue):
            raise RuleParsingError(item)
        return item
