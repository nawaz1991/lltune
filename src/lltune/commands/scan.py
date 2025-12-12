# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Scan (discovery) command."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from ..discovery import collect_snapshot
from ..recommendations import build_recommendations
from ..report import render_markdown


def _write_output(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _render_text(snapshot_dict: Dict[str, Any]) -> str:
    host = snapshot_dict.get("host", {})
    cpu = snapshot_dict.get("cpu", {})
    numa = snapshot_dict.get("numa", {})
    os_name = host.get("os", {}).get("name", "unknown")
    os_ver = host.get("os", {}).get("version_id", "")
    sockets = cpu.get("sockets", 0)
    cores = cpu.get("cores_per_socket", 0)
    threads = cpu.get("threads_per_core", 0)
    gov_count = len(cpu.get("per_cpu_governor", {}))
    numa_nodes = len(numa.get("nodes", []))
    cpu_entries = len(numa.get("cpu_to_node", {}))
    lines = [
        f"Host: {host.get('hostname', 'unknown')}",
        f"Kernel: {host.get('kernel', 'unknown')}",
        f"OS: {os_name} {os_ver}".strip(),
        f"Sockets: {sockets} | Cores/socket: {cores} | Threads: {threads}",
        f"SMT: {cpu.get('smt_enabled', 'unknown')} | Governors: {gov_count} CPUs",
        f"NUMA nodes: {numa_nodes} | CPU->node entries: {cpu_entries}",
    ]
    return "\n".join(lines)


def run_scan(args) -> int:
    """Perform discovery and emit outputs."""
    logger = logging.getLogger("lltune.scan")
    snapshot = collect_snapshot()
    recommendations = build_recommendations(snapshot)
    snapshot_dict = snapshot.to_dict()
    rec_list = [rec.to_dict() for rec in recommendations]
    snapshot_dict_with_recs = dict(snapshot_dict)
    snapshot_dict_with_recs["recommendations"] = rec_list

    fmt = getattr(args, "format", "text") or "text"
    output_path: Optional[Path] = getattr(args, "output", None)

    try:
        if fmt == "text":
            text = _render_text(snapshot_dict)
            if output_path:
                _write_output(output_path, text + "\n")
                logger.info("Wrote text snapshot summary to %s", output_path)
            else:
                sys.stdout.write(text + "\n")
        elif fmt == "json":
            import json

            content = json.dumps(
                snapshot_dict_with_recs, indent=2, sort_keys=True
            )
            if output_path:
                _write_output(output_path, content + "\n")
                logger.info("Wrote JSON snapshot to %s", output_path)
            else:
                sys.stdout.write(content + "\n")
        elif fmt == "yaml":
            content = yaml.safe_dump(snapshot_dict_with_recs, sort_keys=False)
            if output_path:
                _write_output(output_path, content)
                logger.info("Wrote YAML snapshot to %s", output_path)
            else:
                sys.stdout.write(content)
        else:
            logger.error("Unsupported format: %s", fmt)
            return 1

        if getattr(args, "md_report", None):
            md_content = render_markdown(
                snapshot_dict,
                recommendations=recommendations,
                reboot_required=False,
            )
            _write_output(args.md_report, md_content)
            logger.info("Wrote Markdown report to %s", args.md_report)
    except BrokenPipeError:
        # Allow piping to head/tail without stack traces.
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0

    return 0
