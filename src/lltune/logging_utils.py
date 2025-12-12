# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Logging helpers for the CLI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional


DEFAULT_LOG_PATH = Path("/var/log/lltune/lltune.log")


def determine_level(verbose: bool, quiet: bool) -> int:
    """Translate verbosity flags into a logging level."""
    if verbose and quiet:
        raise ValueError("Cannot use --verbose and --quiet together")
    if verbose:
        return logging.DEBUG
    if quiet:
        return logging.WARNING
    return logging.INFO


def setup_logging(
    verbose: bool = False, quiet: bool = False, log_file: Optional[Path] = None
) -> logging.Logger:
    """Configure application logging and return the root logger."""
    level = determine_level(verbose, quiet)

    logger = logging.getLogger("lltune")
    logger.setLevel(level)

    # Avoid duplicate handlers if setup is called multiple times (e.g., tests).
    if logger.handlers:
        for handler in logger.handlers:
            handler.setLevel(level)
        logger.propagate = False
        return logger

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    logger.addHandler(console_handler)

    log_target = log_file or DEFAULT_LOG_PATH
    try:
        log_target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_target)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)
    except OSError:
        # Fall back to console-only logging if file cannot be written.
        logger.warning(
            "Unable to open log file at %s; "
            "continuing with console logging only",
            log_target,
        )

    logger.propagate = False
    return logger
