# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Command-line entrypoint for lltune."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from .commands import run_apply, run_audit, run_gen_config, run_scan
from .commands.rollback import run_rollback
from .env import (
    detect_virtualization,
    is_root,
    is_supported_os,
    read_os_release,
)
from .logging_utils import setup_logging
from .version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lltune", description="Low-Latency System Tuner CLI"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Log file path (default: /var/log/lltune/lltune.log)",
    )

    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v", "--verbose", action="store_true", help="Increase verbosity"
    )
    verbosity.add_argument(
        "-q", "--quiet", action="store_true", help="Reduce verbosity"
    )

    subparsers = parser.add_subparsers(dest="command")

    scan = subparsers.add_parser("scan", help="Run discovery (dry-run)")
    scan.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Path for snapshot output (json/yaml)",
    )
    scan.add_argument(
        "--format",
        choices=["text", "json", "yaml"],
        default="text",
        help="Output format",
    )
    scan.add_argument(
        "--md-report", type=Path, help="Optional Markdown report path"
    )
    scan.set_defaults(func=run_scan)

    gen_config = subparsers.add_parser(
        "gen-config", help="Generate config from snapshot"
    )
    gen_config.add_argument(
        "-o", "--output", type=Path, help="Path for generated YAML config"
    )
    gen_config.add_argument(
        "--snapshot", type=Path, help="Existing snapshot input (optional)"
    )
    gen_config.set_defaults(func=run_gen_config)

    audit = subparsers.add_parser(
        "audit", help="Validate a configuration file"
    )
    audit.add_argument(
        "-c", "--config", type=Path, required=True, help="Config file to audit"
    )
    audit.add_argument(
        "--snapshot", type=Path, help="Optional existing snapshot input"
    )
    audit.add_argument(
        "--output", type=Path, help="Optional JSON output for issues"
    )
    audit.set_defaults(func=run_audit)

    apply_cmd = subparsers.add_parser(
        "apply", help="Apply tuning as per configuration"
    )
    apply_cmd.add_argument(
        "-c", "--config", type=Path, required=True, help="Config file to apply"
    )
    apply_cmd.add_argument(
        "--plan",
        action="store_true",
        help="Show plan without applying changes",
    )
    apply_cmd.add_argument(
        "--validate",
        action="store_true",
        help="Run pre/post validation hooks (cyclictest, IRQ sampling)",
    )
    apply_cmd.add_argument(
        "--quick-validate",
        action="store_true",
        dest="quick_validate",
        help="Use shorter validation durations",
    )
    apply_cmd.set_defaults(func=run_apply)

    rollback_cmd = subparsers.add_parser(
        "rollback", help="Restore configs from a backup bundle"
    )
    rollback_cmd.add_argument(
        "--backup", type=Path, required=True, help="Path to backup bundle"
    )
    rollback_cmd.set_defaults(func=run_rollback)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        args.command = "scan"
        args.func = run_scan
        # Ensure scan options exist on the namespace when subparser not chosen.
        if not hasattr(args, "format"):
            args.format = "text"
        if not hasattr(args, "output"):
            args.output = None
        if not hasattr(args, "md_report"):
            args.md_report = None

    logger = setup_logging(
        verbose=args.verbose, quiet=args.quiet, log_file=args.log_file
    )

    os_info = read_os_release()
    virt = detect_virtualization()

    if os_info:
        logger.debug(
            "Detected OS: %s %s (%s)",
            os_info.name,
            os_info.version_id,
            os_info.os_id,
        )
    else:
        logger.warning(
            "Could not read /etc/os-release; OS detection unavailable"
        )

    if virt:
        logger.info("Virtualization detected: %s", virt)

    if args.command == "apply" and not is_root():
        if getattr(args, "plan", False):
            logger.warning(
                "apply --plan allowed without root; "
                "no system changes will occur."
            )
        else:
            logger.error("apply requires root privileges; aborting")
            return 1

    if args.command in {"apply", "audit"} and not is_supported_os(os_info):
        logger.error("Unsupported OS family for %s; aborting.", args.command)
        return 1

    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        logger.error("Interrupted by user")
        return 1
    except Exception:
        logger.exception("Unhandled exception")
        return 1


if __name__ == "__main__":
    sys.exit(main())
