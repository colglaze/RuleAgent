from __future__ import annotations

from pathlib import Path

import pytest

from rule_reader.domain.rules.errors import ParseErrorCode, RuleParsingError
from rule_reader.infrastructure.documents import LocalDocumentReader


def test_reader_returns_only_relative_source_metadata(tmp_path: Path) -> None:
    root = tmp_path / "rules"
    root.mkdir()
    document_path = root / "示例.md"
    document_path.write_text("# 示例规则\n允许释放。", encoding="utf-8")
    reader = LocalDocumentReader(root, max_characters=1_000)

    document = reader.read(Path("示例.md"))

    assert document.source_name == "示例.md"
    assert document.relative_path == "示例.md"
    assert "允许释放" in document.text


def test_reader_rejects_path_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "rules"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# 外部规则", encoding="utf-8")
    reader = LocalDocumentReader(root, max_characters=1_000)

    with pytest.raises(RuleParsingError) as caught:
        reader.read(outside)

    assert caught.value.issue.code is ParseErrorCode.DOCUMENT_OUTSIDE_ROOT


def test_reader_rejects_non_markdown_file(tmp_path: Path) -> None:
    root = tmp_path / "rules"
    root.mkdir()
    text_file = root / "rule.txt"
    text_file.write_text("rule", encoding="utf-8")
    reader = LocalDocumentReader(root, max_characters=1_000)

    with pytest.raises(RuleParsingError) as caught:
        reader.read(text_file)

    assert caught.value.issue.code is ParseErrorCode.DOCUMENT_TYPE_UNSUPPORTED
