"""Small logging helpers for backend services."""

from __future__ import annotations

import logging


def configure_logging() -> None:
    """Configure a single process-wide logging format."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger."""

    configure_logging()
    return logging.getLogger(name)
