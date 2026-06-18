"""Structured logging setup (structlog + stdlib)."""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from src.config import settings


def configure_logging() -> None:
    """Configure structlog + stdlib logging in JSON-friendly form."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None, **bound: Any) -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.get_logger(name or "nhs", **bound)
