"""Logging configuration using loguru."""

import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_level: str = "INFO", log_dir: str = "data/logs") -> None:
    """Configure loguru logging for the application.

    Sets up two sinks:
    - stderr: colourised, at *log_level* severity.
    - rotating daily file under *log_dir*: DEBUG level, retained 30 days.

    Args:
        log_level: Minimum severity for the console sink (default ``"INFO"``).
        log_dir:   Directory for log files (created automatically if absent).
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
    )
    logger.add(
        log_path / "agent_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    )
