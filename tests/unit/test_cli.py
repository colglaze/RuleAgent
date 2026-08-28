from __future__ import annotations

from rule_reader.cli import _parser


def test_parse_command_accepts_idempotency_key() -> None:
    args = _parser().parse_args(
        [
            "parse",
            "--file",
            "documents/rule.md",
            "--idempotency-key",
            "cli-parse-request-0001",
        ]
    )

    assert args.command == "parse"
    assert args.idempotency_key == "cli-parse-request-0001"
