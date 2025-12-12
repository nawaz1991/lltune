# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""apply command."""

from __future__ import annotations

import logging
from pathlib import Path

from ..apply_engine import apply_config, plan_apply
from ..config_model import load_config
from ..discovery import collect_snapshot
from ..validation_hooks import compare_validation_results, run_validation_hook


def run_apply(args) -> int:
    logger = logging.getLogger("lltune.apply")
    cfg_path: Path = args.config

    try:
        cfg = load_config(cfg_path)
    except Exception:
        logger.exception("Failed to load config %s", cfg_path)
        return 2

    # Collect snapshot for validation hooks
    snapshot_dict = None
    run_validation = getattr(args, "validate", False)

    if args.plan:
        plan, errors = plan_apply(cfg)
        if errors:
            for msg in errors:
                logger.error("[error] %s", msg)
            logger.error("Audit errors present; aborting apply/plan.")
            return 1
        logger.info("Plan mode: no changes applied.")
        logger.info("Backup created at %s", plan.backup_dir)
        if plan.persistence:
            logger.info(
                "Persistence artifacts staged at %s (not installed).",
                plan.persistence.get("root"),
            )
        for step in plan.steps:
            logger.info("[PLAN] %s - %s", step.name, step.detail)
        if plan.reboot_required:
            logger.warning(
                "** REBOOT REQUIRED ** for kernel cmdline changes to take effect."
            )
        return 0

    # Run pre-validation if requested
    pre_validation = None
    if run_validation:
        logger.info("Running pre-apply validation hooks...")
        snapshot_dict = collect_snapshot().to_dict()
        pre_validation = run_validation_hook(
            phase="pre",
            cfg=cfg,
            snapshot=snapshot_dict,
            quick=getattr(args, "quick_validate", False),
        )
        if pre_validation.errors:
            for err in pre_validation.errors:
                logger.warning("Pre-validation: %s", err)
        if pre_validation.latency:
            logger.info(
                "Pre-apply latency: min=%s avg=%s max=%s us",
                pre_validation.latency.min_us,
                pre_validation.latency.avg_us,
                pre_validation.latency.max_us,
            )

    # Apply the configuration
    result = apply_config(cfg, plan_only=False)
    logger.info("Backup created at %s", result.backup_dir)
    if result.persistence:
        logger.info(
            "Persistence artifacts staged at %s (not installed).",
            result.persistence.get("root"),
        )
    for action in result.actions:
        level = logger.info if action.ok else logger.error
        level("[%s] %s", action.name, action.detail)

    if result.reboot_required:
        logger.warning("")
        logger.warning("=" * 60)
        logger.warning(
            "** REBOOT REQUIRED ** for kernel cmdline changes to take effect."
        )
        logger.warning("=" * 60)

    if result.errors:
        for msg in result.errors:
            logger.error("Apply error: %s", msg)
        # Emit rollback instructions
        logger.error("")
        logger.error(
            "To rollback: lltune rollback --backup %s", result.backup_dir
        )
        return 1

    # Run post-validation if requested and apply succeeded
    if run_validation and result.ok:
        logger.info("Running post-apply validation hooks...")
        if snapshot_dict is None:
            snapshot_dict = collect_snapshot().to_dict()
        post_validation = run_validation_hook(
            phase="post",
            cfg=cfg,
            snapshot=snapshot_dict,
            output_dir=result.backup_dir,
            quick=getattr(args, "quick_validate", False),
        )
        if post_validation.errors:
            for err in post_validation.errors:
                logger.warning("Post-validation: %s", err)
        if post_validation.latency:
            logger.info(
                "Post-apply latency: min=%s avg=%s max=%s us",
                post_validation.latency.min_us,
                post_validation.latency.avg_us,
                post_validation.latency.max_us,
            )

        # Compare results if we have both
        if pre_validation:
            comparison = compare_validation_results(
                pre_validation, post_validation
            )
            if comparison:
                logger.info("")
                logger.info("Validation comparison (pre vs post):")
                for key, summary in comparison.items():
                    logger.info("  %s: %s", key, summary)

    logger.info("Apply completed successfully.")
    return 0
