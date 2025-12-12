# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""gen-config command."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ..config_gen import (
    dump_config_yaml,
    generate_config_dict,
    hydrate_snapshot,
)
from ..discovery import collect_snapshot
from ..recommendations import build_recommendations


def run_gen_config(args) -> int:
    """Generate config YAML from snapshot and recommendations."""
    logger = logging.getLogger("lltune.gen_config")

    snapshot = None
    if getattr(args, "snapshot", None):
        snap_path: Path = args.snapshot
        try:
            data = yaml.safe_load(snap_path.read_text())
            snapshot = hydrate_snapshot(data)
            logger.info("Loaded snapshot from %s", snap_path)
        except Exception:
            logger.exception("Failed to load snapshot from %s", snap_path)
            return 1

    if snapshot is None:
        snapshot = collect_snapshot()
        logger.info("Collected live snapshot for config generation")

    recs = build_recommendations(snapshot)
    cfg = generate_config_dict(snapshot, recs)

    if getattr(args, "output", None):
        dump_config_yaml(cfg, args.output)
        logger.info("Wrote config to %s", args.output)
    else:
        text = dump_config_yaml(cfg, None)
        print(text)

    return 0
