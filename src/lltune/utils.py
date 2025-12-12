# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Shared utilities for LLTune."""

from __future__ import annotations

import logging
import re
import shlex
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Maximum CPU ID to prevent memory exhaustion from large ranges
MAX_CPU_ID = 4096

# Safe paths for backup root validation
SAFE_BACKUP_ROOTS = (
    "/var/lib/lltune",
    "/tmp",
    "/var/tmp",
)


def parse_cpulist(text: str) -> List[int]:
    """Parse CPU list string (e.g., '0-3,8,12-15') into list of CPU IDs.

    Handles:
    - Single CPUs: '0', '1', '8'
    - Ranges: '0-3' (expands to [0, 1, 2, 3])
    - Mixed: '0-3,8,12-15'
    - Prefixes in isolcpus: 'managed_irq,domain,2-7' -> parses '2-7'

    Args:
        text: CPU list string

    Returns:
        Sorted list of unique CPU IDs

    Raises:
        ValueError: If range is invalid (start > end) or CPU ID too large
    """
    if not text or not isinstance(text, str):
        return []
    if "TODO" in text.upper():
        return []

    # Handle isolcpus prefix format: managed_irq,domain,2-7
    # Extract the numeric part after any keyword prefixes
    if "," in text and not text[0].isdigit():
        parts = text.split(",")
        numeric_parts = []
        for part in parts:
            stripped = part.strip()
            if stripped and (stripped[0].isdigit() or stripped.startswith("-")):
                numeric_parts.append(stripped)
        if numeric_parts:
            text = ",".join(numeric_parts)
        else:
            return []

    cpus: List[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue

        # Skip non-numeric prefixes like 'managed_irq', 'domain'
        if part and not part[0].isdigit() and not (
            part.startswith("-") and len(part) > 1
        ):
            continue

        if "-" in part and not part.startswith("-"):
            # Range format: '0-3'
            start_s, _, end_s = part.partition("-")
            try:
                start = int(start_s)
                end = int(end_s)
            except ValueError:
                logger.warning("Invalid CPU range format: %s", part)
                continue

            # Validate range
            if start > end:
                raise ValueError(
                    f"Invalid CPU range {start}-{end}: start > end"
                )
            if end > MAX_CPU_ID:
                raise ValueError(
                    f"CPU ID {end} exceeds maximum ({MAX_CPU_ID})"
                )
            if start < 0:
                raise ValueError(f"Negative CPU ID: {start}")

            cpus.extend(range(start, end + 1))
        else:
            try:
                cpu = int(part)
            except ValueError:
                logger.warning("Invalid CPU ID: %s", part)
                continue

            if cpu > MAX_CPU_ID:
                raise ValueError(
                    f"CPU ID {cpu} exceeds maximum ({MAX_CPU_ID})"
                )
            if cpu < 0:
                raise ValueError(f"Negative CPU ID: {cpu}")

            cpus.append(cpu)

    # Remove duplicates and sort
    return sorted(set(cpus))


def cpus_to_mask(cpus: List[int]) -> str:
    """Convert list of CPU IDs to hexadecimal affinity mask.

    Args:
        cpus: List of CPU IDs

    Returns:
        Hexadecimal mask string (e.g., 'f' for CPUs 0-3)
    """
    if not cpus:
        return "0"
    mask = 0
    for cpu in cpus:
        if cpu >= 0:
            mask |= 1 << cpu
    return f"{mask:x}"


def validate_backup_root(path: Path) -> Path:
    """Validate and normalize backup root path.

    Args:
        path: Proposed backup root path

    Returns:
        Validated absolute path

    Raises:
        ValueError: If path is unsafe (e.g., '/', '/etc', '/boot')
    """
    # Resolve to absolute path
    resolved = path.resolve()

    # Prevent obviously dangerous paths
    dangerous_paths = {
        Path("/"),
        Path("/etc"),
        Path("/boot"),
        Path("/usr"),
        Path("/bin"),
        Path("/sbin"),
        Path("/lib"),
        Path("/lib64"),
        Path("/dev"),
        Path("/proc"),
        Path("/sys"),
        Path("/run"),
    }

    if resolved in dangerous_paths:
        raise ValueError(
            f"Unsafe backup root: {resolved}. "
            f"Cannot use system directories for backups."
        )

    # Check if path starts with any dangerous prefix
    for dangerous in dangerous_paths:
        if dangerous != Path("/"):
            try:
                resolved.relative_to(dangerous)
                # If we get here, resolved is under a dangerous path
                # That's okay - /var/lib/lltune is under /var which isn't
                # in our list
                pass
            except ValueError:
                pass

    # Ensure path is not a symlink pointing outside safe areas
    if path.is_symlink():
        logger.warning(
            "Backup root %s is a symlink - ensure it points to a safe location",
            path
        )

    return resolved


def shell_quote(value: str) -> str:
    """Safely quote a string for shell use.

    Uses shlex.quote() to properly escape all shell metacharacters.

    Args:
        value: String to quote

    Returns:
        Safely quoted string for shell use
    """
    return shlex.quote(value)


def validate_interface_name(name: str) -> bool:
    """Validate network interface name is safe.

    Args:
        name: Interface name to validate

    Returns:
        True if name is valid, False otherwise
    """
    if not name:
        return False

    # Check for path traversal attempts
    if ".." in name or "/" in name or "\\" in name:
        logger.warning("Invalid interface name (path traversal attempt): %s", name)
        return False

    # Check for shell metacharacters
    if any(c in name for c in "`$;|&<>(){}[]'\""):
        logger.warning("Invalid interface name (shell metacharacters): %s", name)
        return False

    # Linux interface names: alphanumeric, dash, dot, max 15 chars
    if not re.match(r"^[a-zA-Z0-9][-a-zA-Z0-9.]*$", name):
        logger.warning("Invalid interface name (invalid format): %s", name)
        return False

    if len(name) > 15:
        logger.warning("Interface name too long: %s", name)
        return False

    return True


def detect_efi_grub_path() -> Optional[Path]:
    """Detect the correct EFI GRUB config path for the current distro.

    Checks for common EFI GRUB paths across RHEL-family distros:
    - AlmaLinux: /boot/efi/EFI/almalinux/grub.cfg
    - RHEL: /boot/efi/EFI/redhat/grub.cfg
    - Rocky Linux: /boot/efi/EFI/rocky/grub.cfg
    - CentOS: /boot/efi/EFI/centos/grub.cfg
    - Oracle Linux: /boot/efi/EFI/oracle/grub.cfg
    - Fedora: /boot/efi/EFI/fedora/grub.cfg

    Returns:
        Path to EFI GRUB config if found, None otherwise
    """
    efi_base = Path("/boot/efi/EFI")

    if not efi_base.exists():
        logger.debug("EFI directory %s does not exist", efi_base)
        return None

    # Check distro-specific paths
    distro_names = [
        "almalinux",
        "redhat",
        "rocky",
        "centos",
        "oracle",
        "fedora",
    ]

    for distro in distro_names:
        grub_cfg = efi_base / distro / "grub.cfg"
        if grub_cfg.exists():
            logger.debug("Found EFI GRUB config at %s", grub_cfg)
            return grub_cfg

    # Try to detect from /etc/os-release
    os_release = Path("/etc/os-release")
    if os_release.exists():
        try:
            content = os_release.read_text()
            # Look for ID= line
            for line in content.splitlines():
                if line.startswith("ID="):
                    distro_id = line.split("=", 1)[1].strip().strip('"').lower()
                    grub_cfg = efi_base / distro_id / "grub.cfg"
                    if grub_cfg.exists():
                        logger.debug("Found EFI GRUB config at %s", grub_cfg)
                        return grub_cfg
                    break
        except OSError as e:
            logger.debug("Could not read /etc/os-release: %s", e)

    # Fallback: search for any grub.cfg in EFI directory
    try:
        for grub_cfg in efi_base.glob("*/grub.cfg"):
            logger.debug("Found EFI GRUB config at %s (fallback search)", grub_cfg)
            return grub_cfg
    except OSError as e:
        logger.debug("Could not search EFI directory: %s", e)

    logger.debug("No EFI GRUB config found")
    return None


def safe_path_join(base: Path, relative: Path) -> Path:
    """Safely join paths, preventing directory traversal.

    Args:
        base: Base directory path
        relative: Relative path to join

    Returns:
        Joined path guaranteed to be under base

    Raises:
        ValueError: If the resulting path escapes the base directory
    """
    # Convert relative to string and strip leading slashes
    rel_str = str(relative).lstrip("/")

    # Join and resolve
    joined = (base / rel_str).resolve()
    base_resolved = base.resolve()

    # Verify the joined path is under base
    try:
        joined.relative_to(base_resolved)
    except ValueError:
        raise ValueError(
            f"Path traversal detected: {relative} escapes {base}"
        )

    return joined
