"""Logging configuration."""

from __future__ import annotations

import logging

from rule_reader.core.config import LogLevel


def configure_logging(level: LogLevel) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
