# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Environment and host checks for CLI safeguards."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class OSInfo:
    os_id: str
    version_id: str
    name: str


def read_os_release(path: Path = Path("/etc/os-release")) -> Optional[OSInfo]:
    """Parse /etc/os-release (or compatible) into OSInfo."""
    if not path.exists():
        return None
    data = {}
    for line in path.read_text().splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"')
    os_id = data.get("ID", "").lower()
    version_id = data.get("VERSION_ID", "")
    name = data.get("PRETTY_NAME") or data.get("NAME") or os_id
    return OSInfo(os_id=os_id, version_id=version_id, name=name)


def is_supported_os(info: Optional[OSInfo]) -> bool:
    """Return True if OS matches the primary target (RHEL9-compatible)."""
    if info is None:
        return False
    # Support AlmaLinux, RHEL, Rocky, CentOS Stream, and Oracle Linux 9.x
    supported_ids = {"almalinux", "rhel", "rocky", "centos", "ol"}
    if info.os_id in supported_ids and info.version_id.startswith("9"):
        return True
    return False


def is_root() -> bool:
    """Return True if running as root."""
    return os.geteuid() == 0


def detect_virtualization() -> Optional[str]:
    """Best-effort virtualization detection via systemd-detect-virt."""
    try:
        result = subprocess.run(
            ["systemd-detect-virt", "--quiet", "--print"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None

    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
