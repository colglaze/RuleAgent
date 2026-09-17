"""Extract §1.3/§5.1/§5.2 parse input without copying private bodies into logs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from rule_reader.domain.optimization_plan import (
    EXTRACTED_SECTIONS,
    EXTRACTOR_VERSION,
    OPTIMIZATION_PLAN_FILE_SHA256,
    SECTION_1_3_HEADING,
    SECTION_5_6_HEADING,
)
from rule_reader.domain.rules.v31 import SourceIdentityV31


class SourceIdentityError(ValueError):
    """Raised when the optimization-plan extract cannot be isolated."""


@dataclass(frozen=True, slots=True)
class ExtractedOptimizationPlan:
    source_file_sha256: str
    source_file_byte_length: int
    parse_input: str
    parse_input_sha256: str
    parse_input_character_count: int
    extractor_version: str
    extracted_sections: tuple[str, ...]


def hash_file_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def extract_optimization_plan_sections(source_text: str) -> str:
    start = source_text.find(SECTION_1_3_HEADING)
    if start < 0:
        raise SourceIdentityError("section 1.3 heading is missing")
    end = source_text.find(SECTION_5_6_HEADING, start)
    block = source_text[start:] if end < 0 else source_text[start:end]
    extracted = block.strip()
    if "### 5.1" not in extracted or "### 5.2" not in extracted:
        raise SourceIdentityError("sections 5.1 and 5.2 must be part of the parse input")
    if "ReportZeroAmountRule" not in extracted:
        raise SourceIdentityError("section 5.2 executable examples are missing from parse input")
    return extracted


def build_source_identity(
    file_bytes: bytes,
    source_text: str,
    *,
    expected_file_sha256: str = OPTIMIZATION_PLAN_FILE_SHA256,
) -> tuple[ExtractedOptimizationPlan, SourceIdentityV31]:
    file_sha256 = hash_file_bytes(file_bytes)
    if file_sha256 != expected_file_sha256:
        raise SourceIdentityError("source file hash does not match the frozen optimization plan")
    parse_input = extract_optimization_plan_sections(source_text)
    parse_sha256 = hashlib.sha256(parse_input.encode("utf-8")).hexdigest()
    if parse_sha256 == file_sha256:
        raise SourceIdentityError("parse input hash must not equal the raw file hash")
    extracted = ExtractedOptimizationPlan(
        source_file_sha256=file_sha256,
        source_file_byte_length=len(file_bytes),
        parse_input=parse_input,
        parse_input_sha256=parse_sha256,
        parse_input_character_count=len(parse_input),
        extractor_version=EXTRACTOR_VERSION,
        extracted_sections=EXTRACTED_SECTIONS,
    )
    identity = SourceIdentityV31(
        source_file_sha256=extracted.source_file_sha256,
        parse_input_sha256=extracted.parse_input_sha256,
        extractor_version=extracted.extractor_version,
        extracted_sections=list(extracted.extracted_sections),
        source_file_byte_length=extracted.source_file_byte_length,
        parse_input_character_count=extracted.parse_input_character_count,
    )
    return extracted, identity
