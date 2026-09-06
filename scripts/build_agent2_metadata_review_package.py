"""Build the offline metadata-review package for the 18 exported FactBindingRequest 3.0.0.

Reads the confirmed artifacts (requests + catalog) and produces a sanitized owner-review
package: logical query requirements per request plus evidence locators, so the metadata
owner can approve physical binding and the DBA can capture the real SQL Server metadata
snapshot for SqlBot metadataReview. No MongoDB, DeepSeek, SQL Server, or SqlBot access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from rule_reader.domain.rules.bindings_v3 import FactBindingRequestV3

FIELD_ROLE_LABELS = {
    "value": "取值",
    "entityKey": "实体键",
    "filter": "筛选",
    "groupBy": "分组",
    "time": "时间",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validated_requests(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("fact binding request artifact must be a non-empty JSON array")
    requests = [FactBindingRequestV3.model_validate(item) for item in value]
    request_ids = [item.request_id for item in requests]
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("fact binding request artifact contains duplicate request IDs")
    rule_versions = {item.rule_ref.rule_version for item in requests}
    if len(rule_versions) != 1:
        raise ValueError("all fact binding requests must reference one rule version")
    return [item.model_dump(mode="json", by_alias=True) for item in requests]


def _request_summary(request: dict[str, Any]) -> dict[str, Any]:
    fact = request["fact"]
    query = request["queryRequirements"]
    return {
        "requestId": request["requestId"],
        "factCode": fact["factCode"],
        "factKind": fact["factKind"],
        "dataType": fact["dataType"],
        "grain": fact["grain"],
        "nullable": fact["nullable"],
        "allowedValues": fact.get("allowedValues", []),
        "entity": {
            "entityType": query["entity"]["entityType"],
            "grain": query["entity"]["grain"],
            "keyParameters": query["entity"]["keyParameters"],
        },
        "fields": [
            {
                "fieldId": field["fieldId"],
                "role": field["role"],
                "logicalName": field["logicalName"],
                "dataType": field["dataType"],
                "required": field["required"],
            }
            for field in query["fields"]
        ],
        "filters": [
            {
                "filterId": item["filterId"],
                "fieldId": item["fieldId"],
                "operator": item["operator"],
                "value": item.get("value"),
                "nullPolicy": item["nullPolicy"],
                "required": item["required"],
            }
            for item in query["filters"]["items"]
        ],
        "aggregation": {
            "mode": query["aggregation"]["mode"],
            "function": query["aggregation"].get("function"),
            "inputFieldIds": query["aggregation"].get("inputFieldIds", []),
        },
        "timeRange": {"mode": query["timeRange"]["mode"]},
        "result": {
            "columnName": query["result"]["columnName"],
            "dataType": query["result"]["dataType"],
            "cardinality": query["result"]["cardinality"],
            "nullable": query["result"]["nullable"],
        },
        "usages": [
            {
                "stage": usage["stage"],
                "ruleCode": usage["ruleCode"],
                "priority": usage["priority"],
                "conditionId": usage["conditionId"],
                "outcome": usage["outcome"],
            }
            for usage in request["usages"]
        ],
        "uncertainties": [
            {
                "uncertaintyId": item["uncertaintyId"],
                "code": item["code"],
                "reason": item["reason"],
            }
            for item in request["uncertainties"]
        ],
        "physicalBinding": {
            "mappingStatus": request["mappingCandidate"]["mappingStatus"],
            "note": (
                "物理 relation/column/join 由 metadata owner 批准并在 SqlBot "
                "metadataReview 中解析；本包不携带物理字段。"
            ),
        },
    }


def _markdown(summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# Agent 2 元数据审批材料包（逻辑层）",
        "",
        "来源：已就绪的 RuleParseResultV3 及 18 条 FactBindingRequest 3.0.0（真实 ruleId 与",
        "版本，16/16 readiness 门禁通过）。本包只包含逻辑查询要求与证据定位，",
        "不包含物理字段、SQL、凭据或本机路径。",
        "",
        "## metadata owner 审批步骤",
        "",
        "1. 逐条确认下列事实的实体、粒度、键参数、逻辑字段、筛选、聚合与时间语义；",
        "2. 对每条请求批准其物理绑定方向（真实 SQL Server 库中的表与列），",
        "   由 DBA 以只读方式采集 INFORMATION_SCHEMA 级元数据快照；",
        "3. 快照交 SqlBot metadataReview 阶段解析 mappingCandidate（当前全部 unresolved）；",
        "4. 两个标志位的 0/1 与 4/5 编码差异必须在物理绑定阶段显式裁决。",
        "",
        "## 逐请求清单",
        "",
    ]
    for index, request in enumerate(summaries, start=1):
        fact_code = request["factCode"]
        lines.append(f"### {index}. {fact_code}（{request['factKind']}，{request['dataType']}）")
        lines.append("")
        lines.append(f"- requestId：`{request['requestId']}`")
        entity = request["entity"]
        keys = "，".join(entity["keyParameters"])
        lines.append(f"- 实体/粒度：{entity['entityType']} / {entity['grain']}（键参数：{keys}）")
        fields = "；".join(
            f"{field['fieldId']}（{FIELD_ROLE_LABELS.get(field['role'], field['role'])}，"
            f"{field['dataType']}）"
            for field in request["fields"]
        )
        lines.append(f"- 逻辑字段：{fields}")

        def _filter_text(item: dict[str, Any]) -> str:
            value = item.get("value")
            if value is None:
                bound = "一元条件"
            elif value.get("kind") == "parameter":
                bound = f"参数:{value['parameterName']}"
            else:
                bound = f"字面量:{value['literal']}"
            return f"{item['filterId']} {item['operator']} {bound}"

        filters = "；".join(_filter_text(item) for item in request["filters"])
        lines.append(f"- 筛选（complete）：{filters}")
        aggregation = request["aggregation"]
        lines.append(
            f"- 聚合：{aggregation['mode']}"
            + (
                f" {aggregation['function']}（输入：{', '.join(aggregation['inputFieldIds'])}）"
                if aggregation["function"]
                else ""
            )
        )
        lines.append(f"- 时间范围：{request['timeRange']['mode']}")
        lines.append(
            f"- 结果：{request['result']['columnName']}（{request['result']['dataType']}，"
            f"{request['result']['cardinality']}，nullable={request['result']['nullable']}）"
        )
        usages = "；".join(
            f"{usage['stage']}/{usage['ruleCode']}(p{usage['priority']})→{usage['outcome']}"
            for usage in request["usages"]
        )
        lines.append(f"- 规则引用：{usages}")
        for uncertainty in request["uncertainties"]:
            lines.append(f"- warning：{uncertainty['code']}——{uncertainty['reason']}")
        lines.append("")
    lines.append("## 快照采集要求（DBA）")
    lines.append("")
    lines.append("- 目标：真实 SQL Server 库的 INFORMATION_SCHEMA 级表/列清单，")
    lines.append("  覆盖上述实体与逻辑字段所映射的物理对象；")
    lines.append("- 方式：只读元数据查询；不执行业务 SQL、不取业务数据；")
    lines.append("- 交付：快照文件交 SqlBot metadataReview，并在 owner 批准记录中登记版本。")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirmed-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    requests = _validated_requests(_load(args.confirmed_dir / "fact-binding-requests-3.0.0.json"))
    summaries = [_request_summary(request) for request in requests]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "metadata-review-requests.json"
    md_path = args.output_dir / "metadata-review-package.md"
    json_path.write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    md_path.write_text(_markdown(summaries), encoding="utf-8")
    print(
        json.dumps(
            {
                "requestCount": len(summaries),
                "packageMdSha256": hashlib.sha256(md_path.read_bytes()).hexdigest(),
                "requestsJsonSha256": hashlib.sha256(json_path.read_bytes()).hexdigest(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
