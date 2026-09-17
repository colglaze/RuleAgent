"""Purpose gating so historical V3 batches cannot be used for optimization-plan generation."""

from __future__ import annotations

from enum import StrEnum

HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION = (
    "REPORT_RELEASE_ALL_001@20260905T172407000000Z-f285643e5b2b-82dbd05a800a"
)


class DeliveryPurposeV31(StrEnum):
    HISTORICAL_AUDIT = "historical-audit"
    OPTIMIZATION_PLAN_GENERATION = "optimization-plan-generation"
    SQL_COMPILATION = "sql-compilation"


class DeliveryPurposeDeniedError(ValueError):
    def __init__(self, rule_version: str, purpose: str) -> None:
        super().__init__("Delivery is not available for the requested purpose")
        self.rule_version = rule_version
        self.purpose = purpose


def allowed_purposes_for_rule_version(rule_version: str) -> frozenset[DeliveryPurposeV31]:
    if rule_version == HISTORICAL_REPORT_RELEASE_V3_RULE_VERSION:
        return frozenset({DeliveryPurposeV31.HISTORICAL_AUDIT})
    return frozenset(
        {
            DeliveryPurposeV31.OPTIMIZATION_PLAN_GENERATION,
        }
    )


def assert_delivery_purpose_allowed(rule_version: str, purpose: DeliveryPurposeV31) -> None:
    if purpose not in allowed_purposes_for_rule_version(rule_version):
        raise DeliveryPurposeDeniedError(rule_version, purpose.value)
