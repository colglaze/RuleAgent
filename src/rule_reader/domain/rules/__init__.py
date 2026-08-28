"""Rule parsing contracts and deterministic validation."""

from rule_reader.domain.rules.bindings import FactBindingRequestV1
from rule_reader.domain.rules.bindings_v2 import FactBindingRequestV2
from rule_reader.domain.rules.models import RuleParseResult
from rule_reader.domain.rules.v2 import RuleParseResultV2
from rule_reader.domain.rules.versioned import RuleDocument, validate_rule_document

# Runtime consumers must use the current handoff contract. V1 remains available only
# through its explicit historical name for read-only compatibility tests and tooling.
FactBindingRequest = FactBindingRequestV2

__all__ = [
    "FactBindingRequest",
    "FactBindingRequestV1",
    "FactBindingRequestV2",
    "RuleDocument",
    "RuleParseResult",
    "RuleParseResultV2",
    "validate_rule_document",
]
