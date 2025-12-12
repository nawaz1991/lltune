# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Rollback helper using backup bundle."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import List

from ..apply_engine import (
    GRUB_CFG_BIOS,
    GRUB_DEFAULT,
    SYSCTL_PATH,
    FSTAB_PATH,
)
from ..persistence import (
    IRQ_SERVICE_NAME,
    NIC_SERVICE_NAME,
    THP_SERVICE_NAME,
    WORKQUEUE_SERVICE_NAME,
)
from ..utils import detect_efi_grub_path


def _restore_file(
    backup_root: Path, path: Path, logger: logging.Logger
) -> bool:
    """Restore a single file from the backup bundle."""
    backup = backup_root / "baseline" / path.relative_to("/")
    if not backup.exists():
        logger.warning("Backup missing for %s", path)
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(backup.read_bytes())
        logger.info("Restored %s", path)
        return True
    except OSError as exc:
        logger.error("Failed to restore %s: %s", path, exc)
        return False


def _run_grub_mkconfig(logger: logging.Logger) -> bool:
    """Run grub2-mkconfig to regenerate boot config."""
    grub_mkconfig = shutil.which("grub2-mkconfig") or shutil.which(
        "grub-mkconfig"
    )
    if not grub_mkconfig:
        logger.warning(
            "grub2-mkconfig not found; cannot regenerate boot config"
        )
        return False

    # Determine output path (use dynamic EFI detection)
    efi_grub = detect_efi_grub_path()
    if efi_grub:
        output = str(efi_grub)
    elif GRUB_CFG_BIOS.exists():
        output = str(GRUB_CFG_BIOS)
    else:
        logger.warning("No grub.cfg found to regenerate")
        return False

    logger.info("Regenerating GRUB config: %s -o %s", grub_mkconfig, output)
    try:
        result = subprocess.run(
            [grub_mkconfig, "-o", output],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.error("grub2-mkconfig failed: %s", result.stderr)
            return False
        logger.info("GRUB config regenerated successfully")
        return True
    except subprocess.TimeoutExpired:
        logger.error("grub2-mkconfig timed out")
        return False
    except OSError as exc:
        logger.error("Failed to run grub2-mkconfig: %s", exc)
        return False


def _disable_lltune_services(logger: logging.Logger) -> None:
    """Disable and remove lltune persistence services if installed."""
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return

    services = [
        NIC_SERVICE_NAME,
        THP_SERVICE_NAME,
        IRQ_SERVICE_NAME,
        WORKQUEUE_SERVICE_NAME,
    ]
    for svc in services:
        svc_path = Path("/etc/systemd/system") / svc
        if svc_path.exists():
            logger.info("Disabling and removing %s", svc)
            try:
                subprocess.run(
                    [systemctl, "disable", "--now", svc],
                    capture_output=True,
                    timeout=30,
                )
                svc_path.unlink()
            except (subprocess.TimeoutExpired, OSError) as exc:
                logger.warning("Failed to remove %s: %s", svc, exc)

    # Reload systemd after removing units
    try:
        subprocess.run(
            [systemctl, "daemon-reload"], capture_output=True, timeout=30
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


def _restore_sysctl_runtime(backup_root: Path, logger: logging.Logger) -> None:
    """Re-apply sysctl values from backed up config."""
    sysctl_bin = shutil.which("sysctl")
    if not sysctl_bin:
        return

    backup_sysctl = (
        backup_root / "baseline" / "etc" / "sysctl.d" / "99-latency-tuner.conf"
    )
    if not backup_sysctl.exists():
        return

    logger.info("Reloading sysctl settings")
    try:
        subprocess.run(
            [sysctl_bin, "--system"], capture_output=True, timeout=30
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Failed to reload sysctl: %s", exc)


def run_rollback(args) -> int:
    """Execute rollback from a backup bundle.

    This will:
    1. Restore backed up configuration files
    2. Optionally regenerate GRUB config
    3. Disable lltune persistence services
    4. Reload sysctl settings

    A reboot is required after rollback for GRUB/kernel changes to take effect.
    """
    logger = logging.getLogger("lltune.rollback")
    bundle = Path(args.backup).expanduser()
    if not bundle.exists():
        logger.error("Backup bundle not found: %s", bundle)
        return 1

    # Restore configuration files
    targets: List[Path] = [GRUB_DEFAULT, SYSCTL_PATH, FSTAB_PATH]
    restored_any = False
    restored_grub = False

    for path in targets:
        if _restore_file(bundle, path, logger):
            restored_any = True
            if path == GRUB_DEFAULT:
                restored_grub = True

    # Regenerate GRUB config if we restored GRUB defaults
    if restored_grub:
        auto_regen = getattr(args, "regenerate_grub", True)
        if auto_regen:
            _run_grub_mkconfig(logger)
        else:
            logger.info("Skipping grub2-mkconfig; run manually if needed")

    # Disable lltune services
    if getattr(args, "disable_services", True):
        _disable_lltune_services(logger)

    # Reload sysctl
    _restore_sysctl_runtime(bundle, logger)

    if restored_any:
        logger.info(
            "Rollback complete. A REBOOT is required for kernel cmdline changes to take effect."
        )
        logger.info("Manual steps may be needed:")
        logger.info(
            "  - Re-enable irqbalance if previously disabled: systemctl enable --now irqbalance"
        )
        logger.info(
            "  - Restore NIC settings to defaults (driver reload or ethtool)"
        )
        logger.info(
            "  - Re-enable tuned if previously stopped: systemctl enable --now tuned"
        )
        return 0
    else:
        logger.warning("No files were restored from backup")
        return 1
