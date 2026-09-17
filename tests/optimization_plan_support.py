"""Synthetic source identity for optimization-plan 3.1.0 offline tests."""

from __future__ import annotations

from rule_reader.domain.optimization_plan.extractor import build_source_identity, hash_file_bytes
from rule_reader.domain.rules.v31 import SourceIdentityV31

SYNTHETIC_OPTIMIZATION_PLAN = """# Synthetic optimization plan

### 1.3 Rule structure
Report flags, R0-R9, merge group, OA, D0-D4.

### 5.1 Amount basis
Completed amount and arrival including deposit.

### 5.2 Executable examples
public class ReportZeroAmountRule {}
D0-D4 and R3 tier formulas live here.

### 5.6 Out of extract
Not part of the parse input.
"""


def synthetic_source_identity() -> SourceIdentityV31:
    payload = SYNTHETIC_OPTIMIZATION_PLAN.encode("utf-8")
    _extracted, identity = build_source_identity(
        payload,
        SYNTHETIC_OPTIMIZATION_PLAN,
        expected_file_sha256=hash_file_bytes(payload),
    )
    return identity
