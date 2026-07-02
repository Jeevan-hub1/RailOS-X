"""
RailOS Shared Logging Configuration
=====================================
Provides a standard JSON-structured logging setup used across all services.
"""
from __future__ import annotations

import logging

# Standard JSON log format used across all RailOS services
_JSON_FORMAT = '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def configure_logging(level: int = logging.INFO) -> None:
    """Apply the standard RailOS JSON logging configuration."""
    logging.basicConfig(level=level, format=_JSON_FORMAT, datefmt=_DATE_FORMAT)
