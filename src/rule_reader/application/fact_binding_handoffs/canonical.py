"""Canonical FactBindingRequest payload serialization and hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from rule_reader.domain.rules.bindings_v2 import FactBindingRequestV2

Payload = dict[str, Any]


def fact_binding_payload(request: FactBindingRequestV2) -> Payload:
    """Return the complete public camelCase payload used for storage and hashing."""

    return request.model_dump(by_alias=True, mode="json")


def canonical_payload_json(payload: Payload) -> str:
    """Serialize one payload with the frozen handoff canonicalization rules."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_payload_sha256(payload: Payload) -> str:
    return hashlib.sha256(canonical_payload_json(payload).encode("utf-8")).hexdigest()
