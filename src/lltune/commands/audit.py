# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""audit command."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from ..config_model import load_config, validate_cross, validate_schema
from ..discovery import collect_snapshot


def run_audit(args) -> int:
    logger = logging.getLogger("lltune.audit")
    cfg_path: Path = args.config

    try:
        cfg = load_config(cfg_path)
    except Exception:
        logger.exception("Failed to load config %s", cfg_path)
        return 2

    schema_res = validate_schema(cfg)

    snapshot = None
    if getattr(args, "snapshot", None):
        try:
            data = yaml.safe_load(args.snapshot.read_text())
            snapshot = data if isinstance(data, dict) else None
        except Exception:
            logger.exception("Failed to load snapshot %s", args.snapshot)
            return 3
    if snapshot is None:
        snapshot = collect_snapshot().to_dict()

    cross_res = validate_cross(cfg, snapshot)

    issues = schema_res.issues + cross_res.issues
    for issue in issues:
        logger_method = (
            logger.error if issue.severity == "error" else logger.warning
        )
        logger_method(
            "[%s] %s: %s", issue.severity, issue.field, issue.message
        )

    if getattr(args, "output", None):
        output = {"issues": [issue.__dict__ for issue in issues]}
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        logger.info("Wrote audit issues to %s", args.output)

    return 1 if any(i.severity == "error" for i in issues) else 0
