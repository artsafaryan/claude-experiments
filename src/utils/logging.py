"""Logging configuration."""

import logging
import sys
from typing import Optional

from .config import get_settings


def setup_logging(level: Optional[str] = None) -> logging.Logger:
    """Configure and return the application logger."""
    settings = get_settings()
    log_level = level or settings.log_level

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Get root logger
    logger = logging.getLogger("influencer_automation")
    logger.setLevel(getattr(logging, log_level.upper()))
    logger.addHandler(console_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a named logger."""
    return logging.getLogger(f"influencer_automation.{name}")
