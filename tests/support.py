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


def valid_candidate_v2(*, rule_id: str = "TEST_RELEASE_002") -> dict[str, Any]:
    task_parameter = {
        "name": "taskId",
        "dataType": "integer",
        "description": "正式实验任务 ID",
        "required": True,
    }
    unresolved = {
        "mappingStatus": "unresolved",
        "viewName": None,
        "viewField": None,
        "note": "等待 Agent 2 结合 SQL Server 元数据确认。",
    }
    return {
        "ruleId": rule_id,
        "title": "测试释放规则 2.0",
        "scope": "适用于正式实验任务的结构化金额判断。",
        "entityType": "formal_test_task",
        "sourceViews": ["v_test_release", "v_OrderFormaltestsettlement"],
        "requiredFacts": [
            {
                "factCode": "task.status",
                "name": "任务状态",
                "factKind": "source",
                "dataType": "integer",
                "description": "当前正式实验任务状态",
                "nullable": False,
                "nullPolicy": "error",
                "grain": "formal_test_task",
                "parameters": [task_parameter],
            },
            {
                "factCode": "task.received_amount",
                "name": "累计到款",
                "factKind": "aggregate",
                "dataType": "money",
                "description": "任务所属订单累计到款金额",
                "nullable": False,
                "nullPolicy": "fail",
                "grain": "formal_test_task",
                "parameters": [task_parameter],
                "unit": "CNY",
            },
            {
                "factCode": "task.base_fee",
                "name": "基础费用",
                "factKind": "aggregate",
                "dataType": "money",
                "description": "任务基础费用",
                "nullable": False,
                "nullPolicy": "error",
                "grain": "formal_test_task",
                "parameters": [task_parameter],
                "unit": "CNY",
            },
            {
                "factCode": "task.extra_fee",
                "name": "附加费用",
                "factKind": "aggregate",
                "dataType": "money",
                "description": "任务附加费用",
                "nullable": False,
                "nullPolicy": "error",
                "grain": "formal_test_task",
                "parameters": [task_parameter],
                "unit": "CNY",
            },
            {
                "factCode": "task.required_fee",
                "name": "应覆盖费用",
                "factKind": "derived",
                "dataType": "money",
                "description": "基础费用与附加费用之和",
                "nullable": False,
                "nullPolicy": "error",
                "grain": "formal_test_task",
                "parameters": [],
                "unit": "CNY",
                "derivation": {
                    "kind": "add",
                    "children": [
                        {"kind": "fact", "factCode": "task.base_fee"},
                        {"kind": "fact", "factCode": "task.extra_fee"},
                    ],
                },
            },
            {
                "factCode": "task.settlement_fee",
                "name": "任务结算费用",
                "factKind": "source",
                "dataType": "money",
                "description": "正式实验任务最终采用费用",
                "nullable": False,
                "nullPolicy": "error",
                "grain": "formal_test_task",
                "parameters": [task_parameter],
                "unit": "CNY",
            },
        ],
        "rootCondition": {
            "id": "root",
            "kind": "all",
            "description": "状态和金额条件全部满足",
            "children": [
                {
                    "id": "task-finished",
                    "kind": "compare",
                    "description": "任务状态为完成",
                    "left": {"kind": "fact", "factCode": "task.status"},
                    "operator": "eq",
                    "right": {"kind": "literal", "value": 19},
                    "nullPolicy": "fail",
                },
                {
                    "id": "amount-covered",
                    "kind": "compare",
                    "description": "累计到款加容差覆盖应覆盖费用",
                    "left": {
                        "kind": "add",
                        "children": [
                            {"kind": "fact", "factCode": "task.received_amount"},
                            {"kind": "literal", "value": 0.1},
                        ],
                    },
                    "operator": "gte",
                    "right": {"kind": "fact", "factCode": "task.required_fee"},
                    "nullPolicy": "fail",
                },
                {
                    "id": "settlement-non-negative",
                    "kind": "compare",
                    "description": "任务结算费用非负",
                    "left": {"kind": "fact", "factCode": "task.settlement_fee"},
                    "operator": "gte",
                    "right": {"kind": "literal", "value": 0},
                    "nullPolicy": "fail",
                },
            ],
        },
        "exceptionNotes": ["特殊申请仍需人工审核。"],
        "failureReasons": ["任务状态或金额条件不满足。"],
        "recommendations": ["核对任务状态、到款和费用。"],
        "responsibleRoles": ["项目负责人"],
        "testCases": [
            {
                "id": "pass-case",
                "description": "状态完成且金额覆盖",
                "given": {
                    "task.status": 19,
                    "task.received_amount": 100,
                    "task.base_fee": 70,
                    "task.extra_fee": 30,
                    "task.settlement_fee": 100,
                },
                "expected": "pass",
                "rationale": "100+0.1 大于等于 70+30",
            },
            {
                "id": "fail-case",
                "description": "金额未覆盖",
                "given": {
                    "task.status": 19,
                    "task.received_amount": 99,
                    "task.base_fee": 70,
                    "task.extra_fee": 30,
                    "task.settlement_fee": 100,
                },
                "expected": "fail",
                "rationale": "99+0.1 小于 70+30",
            },
        ],
        "fieldMappings": [
            {"factCode": "task.status", **unresolved},
            {"factCode": "task.received_amount", **unresolved},
            {"factCode": "task.base_fee", **unresolved},
            {"factCode": "task.extra_fee", **unresolved},
            {"factCode": "task.required_fee", **unresolved},
            {
                "factCode": "task.settlement_fee",
                "mappingStatus": "mapped",
                "viewName": "v_OrderFormaltestsettlement",
                "viewField": "zssyjsfy",
                "note": "使用正式实验任务最终采用费用。",
            },
        ],
        "warnings": ["所有映射均需人工审核。"],
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
