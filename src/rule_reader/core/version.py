"""Application version and supported runtime."""

from __future__ import annotations

import sys

__version__ = "0.12.0"
SUPPORTED_PYTHON = (3, 11, 9)


def ensure_supported_python() -> None:
    """Fail fast when the process does not use the project runtime."""

    actual = sys.version_info[:3]
    if actual != SUPPORTED_PYTHON:
        expected_text = ".".join(str(part) for part in SUPPORTED_PYTHON)
        actual_text = ".".join(str(part) for part in actual)
        raise RuntimeError(f"RuleReader requires Python {expected_text}; found {actual_text}")
