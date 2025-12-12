# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Apply engine with planning, backups, and execution."""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config_model import validate_cross, validate_schema
from .discovery import collect_snapshot, parse_cmdline
from .persistence import write_persistence_bundle
from .shell import run_cmd
from .utils import (
    detect_efi_grub_path,
    parse_cpulist,
    safe_path_join,
    validate_backup_root,
)

logger = logging.getLogger(__name__)

SYSCTL_PATH = Path("/etc/sysctl.d/99-latency-tuner.conf")
GRUB_DEFAULT = Path("/etc/default/grub")
GRUB_CFG_BIOS = Path("/boot/grub2/grub.cfg")
FSTAB_PATH = Path("/etc/fstab")


def _backup_root() -> Path:
    """Get and validate the backup root directory.

    Uses LLTUNE_BACKUP_ROOT environment variable or default /var/lib/lltune/backups.
    Validates that the path is safe (not a system directory).

    Returns:
        Validated backup root path

    Raises:
        ValueError: If backup root path is unsafe
    """
    root_str = os.environ.get("LLTUNE_BACKUP_ROOT", "/var/lib/lltune/backups")
    root = Path(root_str)
    return validate_backup_root(root)


@dataclass
class PlanStep:
    name: str
    detail: str


@dataclass
class ApplyPlan:
    steps: List[PlanStep]
    backup_dir: Path
    persistence: Dict[str, Path]
    snapshot: Dict
    reboot_required: bool = False


@dataclass
class ActionResult:
    name: str
    ok: bool
    detail: str
    reboot_required: bool = False
    touched_files: List[Path] = field(default_factory=list)


@dataclass
class ApplyResult:
    ok: bool
    backup_dir: Path
    actions: List[ActionResult]
    errors: List[str]
    reboot_required: bool
    persistence: Dict[str, Path]


def _backup_file(src: Path, backup_dir: Path, touched: List[Path]) -> None:
    """Backup a file before modification.

    Args:
        src: Source file path to backup
        backup_dir: Root backup directory
        touched: List to track files that were backed up

    Note:
        Uses try/except instead of exists() check to avoid TOCTOU race.
        Validates destination path to prevent directory traversal.
    """
    baseline_dir = backup_dir / "baseline"
    try:
        # Use safe_path_join to prevent path traversal
        dest = safe_path_join(baseline_dir, src)
    except ValueError as e:
        logger.warning("Skipping backup of %s: %s", src, e)
        return

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        touched.append(src)
    except FileNotFoundError:
        # File doesn't exist - nothing to backup (TOCTOU safe)
        pass
    except OSError as e:
        logger.warning("Failed to backup %s: %s", src, e)


def _restore_files(touched: List[Path], backup_dir: Path) -> None:
    """Restore files from backup during rollback.

    Args:
        touched: List of files that were modified
        backup_dir: Root backup directory
    """
    baseline_dir = backup_dir / "baseline"
    for src in touched:
        try:
            backup = safe_path_join(baseline_dir, src)
        except ValueError as e:
            logger.warning("Skipping restore of %s: %s", src, e)
            continue

        try:
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, src)
            logger.debug("Restored %s from backup", src)
        except FileNotFoundError:
            logger.warning("Backup not found for %s", src)
        except OSError as e:
            logger.error("Failed to restore %s: %s", src, e)


def _write_text(
    path: Path, content: str, backup_dir: Path, touched: List[Path]
) -> None:
    _backup_file(path, backup_dir, touched)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text()
        if existing == content:
            return
    path.write_text(content)


def make_backup_dir(root: Optional[Path] = None) -> Path:
    root = root or _backup_root()
    ts = time.strftime("%Y%m%d%H%M%S")
    backup_dir = root / f"backup-{ts}"
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir
    except PermissionError:
        home_fallback = Path.home() / ".lltune" / "backups" / f"backup-{ts}"
        home_fallback.mkdir(parents=True, exist_ok=True)
        return home_fallback


def write_backup_bundle(backup_dir: Path, cfg: Dict, snapshot: Dict) -> None:
    import yaml

    (backup_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False)
    )
    (backup_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2))


def _capture_baseline_files(backup_dir: Path) -> None:
    """Capture baseline system files before applying changes.

    Uses dynamic EFI GRUB path detection to support multiple distros.
    Uses TOCTOU-safe approach with try/except instead of exists() check.
    """
    baseline_dir = backup_dir / "baseline"

    # Build list of files to backup, with dynamic EFI detection
    files_to_backup: List[Path] = [
        GRUB_DEFAULT,
        GRUB_CFG_BIOS,
        SYSCTL_PATH,
        FSTAB_PATH,
    ]

    # Add dynamically detected EFI GRUB path
    efi_grub = detect_efi_grub_path()
    if efi_grub:
        files_to_backup.append(efi_grub)

    for src in files_to_backup:
        try:
            dest = safe_path_join(baseline_dir, src)
        except ValueError as e:
            logger.warning("Skipping backup of %s: %s", src, e)
            continue

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            logger.debug("Backed up %s", src)
        except FileNotFoundError:
            # File doesn't exist - skip (TOCTOU safe)
            pass
        except PermissionError:
            logger.debug("Permission denied backing up %s", src)
        except OSError as e:
            logger.warning("Failed to backup %s: %s", src, e)


def _collect_ethtool_baseline(backup_dir: Path, snapshot: Dict) -> None:
    nic_dir = backup_dir / "baseline" / "ethtool"
    nic_dir.mkdir(parents=True, exist_ok=True)
    for nic in snapshot.get("nics", []):
        name = nic.get("name")
        if not name:
            continue
        for arg, suffix in [
            ("-k", "features"),
            ("-c", "coalesce"),
            ("-g", "rings"),
            ("-a", "flowctrl"),
        ]:
            res = run_cmd(["ethtool", arg, name])
            if res.ok:
                (nic_dir / f"{name}.{suffix}").write_text(res.stdout)


def build_plan(
    cfg: Dict, persistence: Optional[Dict[str, Path]] = None
) -> List[PlanStep]:
    steps: List[PlanStep] = []
    steps.append(
        PlanStep(
            "services", "Disable irqbalance; set tuned profile if configured."
        )
    )
    steps.append(
        PlanStep("memory", "Disable swap; disable THP; configure hugepages.")
    )
    steps.append(
        PlanStep(
            "sysctl",
            "Write sysctl snippet for NUMA balancing/ksm/etc and apply.",
        )
    )
    steps.append(PlanStep("cpu", "Set CPU governors and power settings."))
    steps.append(
        PlanStep(
            "irq",
            "Pin IRQ affinities per config; disable RPS/RFS if configured.",
        )
    )
    steps.append(
        PlanStep(
            "nic", "Apply ethtool offloads, coalescing, ring sizes, RSS/XPS."
        )
    )
    steps.append(
        PlanStep(
            "kernel",
            (
                "Merge GRUB cmdline and regenerate grub.cfg (reboot required)."
                if (cfg.get("kernel", {}) or {}).get("cmdline")
                and (cfg.get("safety", {}) or {}).get("allow_grub_edit", False)
                else (
                    "Kernel cmdline present but skipped (allow_grub_edit=false)."
                    if (cfg.get("kernel", {}) or {}).get("cmdline")
                    else "no kernel cmdline changes"
                )
            ),
        )
    )
    steps.append(
        PlanStep(
            "time", "Validate PTP/NTP services; generate configs if enabled."
        )
    )
    steps.append(
        PlanStep(
            "onload/vma/rdma",
            "Generate env skeletons and validate device alignment.",
        )
    )
    if persistence and persistence.get("root"):
        steps.append(
            PlanStep(
                "persistence",
                f"Boot persistence artifacts staged at {
                    persistence['root']} (not installed).",
            )
        )
    return steps


def plan_apply(
    cfg: Dict, backup_root: Optional[Path] = None
) -> Tuple[ApplyPlan, List[str]]:
    snapshot_obj = collect_snapshot()
    snapshot = snapshot_obj.to_dict()
    issues = validate_schema(cfg).issues + validate_cross(cfg, snapshot).issues
    kernel_cfg = cfg.get("kernel", {}) or {}
    cmd_cfg = kernel_cfg.get("cmdline", {}) or {}
    safety = cfg.get("safety", {}) or {}
    allow_grub = safety.get("allow_grub_edit", False)
    backup_dir = make_backup_dir(backup_root)
    write_backup_bundle(backup_dir, cfg, snapshot)
    _capture_baseline_files(backup_dir)
    _collect_ethtool_baseline(backup_dir, snapshot)
    persistence = write_persistence_bundle(cfg, snapshot, backup_dir)
    steps = build_plan(cfg, persistence)
    # Determine if reboot is required (kernel cmdline changes)
    reboot_required = bool(cmd_cfg and allow_grub)
    return ApplyPlan(
        steps=steps,
        backup_dir=backup_dir,
        persistence=persistence,
        snapshot=snapshot,
        reboot_required=reboot_required,
    ), [i.message for i in issues if i.severity == "error"]


def _sysctl_lines(cfg: Dict) -> List[str]:
    lines: List[str] = []
    memory = cfg.get("memory", {}) or {}
    if "numa_balancing" in memory:
        lines.append(
            f"kernel.numa_balancing={
                '1' if memory.get('numa_balancing') else '0'}"
        )
    swap_disable = memory.get("swap_disable")
    if swap_disable:
        lines.append("vm.swappiness=0")
    ksm = memory.get("ksm")
    if ksm is not None:
        lines.append(f"vm.ksm_run={'1' if ksm else '0'}")

    # Memory locking and VM settings
    mlock = memory.get("mlock", {}) or {}
    if mlock.get("max_map_count"):
        lines.append(f"vm.max_map_count={mlock['max_map_count']}")

    # Dirty page writeback tuning
    if memory.get("dirty_ratio") is not None:
        lines.append(f"vm.dirty_ratio={memory['dirty_ratio']}")
    if memory.get("dirty_background_ratio") is not None:
        lines.append(
            f"vm.dirty_background_ratio={
                memory['dirty_background_ratio']}"
        )
    # VM statistics interval (reduces overhead on isolated cores)
    if memory.get("stat_interval") is not None:
        lines.append(f"vm.stat_interval={memory['stat_interval']}")

    # Network sysctl settings
    network = cfg.get("network", {}) or {}
    sysctl_cfg = network.get("sysctl", {}) or {}

    # Buffer sizes
    if sysctl_cfg.get("rmem_max") is not None:
        lines.append(f"net.core.rmem_max={sysctl_cfg['rmem_max']}")
    if sysctl_cfg.get("wmem_max") is not None:
        lines.append(f"net.core.wmem_max={sysctl_cfg['wmem_max']}")
    if sysctl_cfg.get("rmem_default") is not None:
        lines.append(f"net.core.rmem_default={sysctl_cfg['rmem_default']}")
    if sysctl_cfg.get("wmem_default") is not None:
        lines.append(f"net.core.wmem_default={sysctl_cfg['wmem_default']}")
    if sysctl_cfg.get("tcp_rmem") is not None:
        lines.append(f"net.ipv4.tcp_rmem={sysctl_cfg['tcp_rmem']}")
    if sysctl_cfg.get("tcp_wmem") is not None:
        lines.append(f"net.ipv4.tcp_wmem={sysctl_cfg['tcp_wmem']}")
    if sysctl_cfg.get("udp_rmem_min") is not None:
        lines.append(f"net.ipv4.udp_rmem_min={sysctl_cfg['udp_rmem_min']}")
    if sysctl_cfg.get("udp_wmem_min") is not None:
        lines.append(f"net.ipv4.udp_wmem_min={sysctl_cfg['udp_wmem_min']}")

    # Low latency TCP settings
    if sysctl_cfg.get("tcp_timestamps") is not None:
        val = 1 if sysctl_cfg["tcp_timestamps"] else 0
        lines.append(f"net.ipv4.tcp_timestamps={val}")
    if sysctl_cfg.get("tcp_sack") is not None:
        val = 1 if sysctl_cfg["tcp_sack"] else 0
        lines.append(f"net.ipv4.tcp_sack={val}")
    if sysctl_cfg.get("tcp_low_latency") is not None:
        val = 1 if sysctl_cfg["tcp_low_latency"] else 0
        lines.append(f"net.ipv4.tcp_low_latency={val}")
    if sysctl_cfg.get("tcp_fastopen") is not None:
        lines.append(f"net.ipv4.tcp_fastopen={sysctl_cfg['tcp_fastopen']}")
    if sysctl_cfg.get("tcp_tw_reuse") is not None:
        val = 1 if sysctl_cfg["tcp_tw_reuse"] else 0
        lines.append(f"net.ipv4.tcp_tw_reuse={val}")
    if sysctl_cfg.get("tcp_fin_timeout") is not None:
        lines.append(
            f"net.ipv4.tcp_fin_timeout={
                sysctl_cfg['tcp_fin_timeout']}"
        )

    # Busy polling (critical for HFT)
    if sysctl_cfg.get("busy_poll") is not None:
        lines.append(f"net.core.busy_poll={sysctl_cfg['busy_poll']}")
    if sysctl_cfg.get("busy_read") is not None:
        lines.append(f"net.core.busy_read={sysctl_cfg['busy_read']}")

    # Backlog and queuing
    if sysctl_cfg.get("netdev_max_backlog") is not None:
        lines.append(
            f"net.core.netdev_max_backlog={
                sysctl_cfg['netdev_max_backlog']}"
        )
    if sysctl_cfg.get("netdev_budget") is not None:
        lines.append(f"net.core.netdev_budget={sysctl_cfg['netdev_budget']}")
    if sysctl_cfg.get("somaxconn") is not None:
        lines.append(f"net.core.somaxconn={sysctl_cfg['somaxconn']}")

    # File descriptor limits
    if sysctl_cfg.get("file_max") is not None:
        lines.append(f"fs.file-max={sysctl_cfg['file_max']}")

    return lines


def _apply_services(
    cfg: Dict, backup_dir: Path, plan_only: bool
) -> ActionResult:
    svc_cfg = cfg.get("services", {}) or {}
    detail_lines: List[str] = []
    if svc_cfg.get("irqbalance") is False:
        detail_lines.append("disable irqbalance")
        if not plan_only:
            run_cmd(["systemctl", "disable", "--now", "irqbalance"])
    tuned_profile = svc_cfg.get("tuned")
    if tuned_profile:
        detail_lines.append(f"set tuned profile {tuned_profile}")
        if not plan_only:
            run_cmd(["tuned-adm", "profile", str(tuned_profile)])
    return ActionResult(
        name="services",
        ok=True,
        detail="; ".join(detail_lines) or "no changes",
        touched_files=[],
    )


def _apply_memory(
    cfg: Dict, snapshot: Dict, backup_dir: Path, plan_only: bool
) -> ActionResult:
    mem_cfg = cfg.get("memory", {}) or {}
    swap_disable = mem_cfg.get("swap_disable")
    touched: List[Path] = []
    details: List[str] = []

    if swap_disable is not None and not isinstance(swap_disable, bool):
        logger.warning(
            "Ignoring memory.swap_disable=%r (must be boolean)", swap_disable
        )
        swap_disable = None

    if swap_disable is True:
        for swap in snapshot.get("memory", {}).get("swap_devices", []):
            dev = swap.get("device")
            if dev:
                details.append(f"swapoff {dev}")
                if not plan_only:
                    run_cmd(["swapoff", dev])
        if FSTAB_PATH.exists():
            content = FSTAB_PATH.read_text().splitlines()
            updated = []
            changed = False
            for line in content:
                if line.strip().startswith("#"):
                    updated.append(line)
                    continue
                fields = line.split()
                is_swap_entry = len(fields) >= 3 and (
                    fields[1] == "swap" or fields[2] == "swap"
                )
                if is_swap_entry:
                    updated.append(f"# lltune disabled swap: {line}")
                    changed = True
                else:
                    updated.append(line)
            if changed and not plan_only:
                _write_text(
                    FSTAB_PATH, "\n".join(updated) + "\n", backup_dir, touched
                )

    thp_mode = mem_cfg.get("thp_runtime")
    if thp_mode:
        details.append(f"set THP to {thp_mode}")
        if not plan_only:
            for fname in ["enabled", "defrag"]:
                path = Path("/sys/kernel/mm/transparent_hugepage") / fname
                if path.exists():
                    _write_text(path, str(thp_mode), backup_dir, touched)

    hp_cfg = mem_cfg.get("hugepages", {}) or {}
    if not isinstance(hp_cfg, dict):
        logger.warning("Ignoring memory.hugepages=%r (must be mapping)", hp_cfg)
        hp_cfg = {}

    size_kb_raw = str(hp_cfg.get("size_kb", "") or "").strip()
    size_kb = (
        ""
        if ("TODO" in size_kb_raw.upper())
        else size_kb_raw
    )
    try:
        size_kb_int = int(size_kb) if size_kb else None
    except ValueError:
        logger.warning("Invalid hugepages.size_kb=%r; skipping", size_kb_raw)
        size_kb_int = None

    total_raw = hp_cfg.get("total")
    total: Optional[int]
    if total_raw is None or (
        isinstance(total_raw, str) and "TODO" in total_raw.upper()
    ):
        total = None
    else:
        try:
            total = int(total_raw)
        except (TypeError, ValueError):
            logger.warning("Invalid hugepages.total=%r; skipping", total_raw)
            total = None

    per_node_cfg: Dict[str, int] = {}
    per_node_raw = hp_cfg.get("per_node", {}) or {}
    if isinstance(per_node_raw, dict):
        for node, count in per_node_raw.items():
            node_name = str(node).strip()
            if not node_name:
                continue
            if not node_name.startswith("node"):
                node_name = f"node{node_name}"
            if isinstance(count, str) and "TODO" in count.upper():
                continue
            try:
                per_node_cfg[node_name] = int(count)
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid hugepages.per_node[%r]=%r; skipping",
                    node,
                    count,
                )
    elif per_node_raw:
        logger.warning(
            "Ignoring hugepages.per_node=%r (must be mapping)", per_node_raw
        )

    if size_kb_int is not None and (total is not None or per_node_cfg):
        details.append(f"configure hugepages {size_kb_int}kB")
        if not plan_only:
            hp_root = Path("/sys/kernel/mm/hugepages")
            hp_dir = hp_root / f"hugepages-{size_kb_int}kB"
            if hp_dir.exists() and total is not None:
                _write_text(
                    hp_dir / "nr_hugepages", str(total), backup_dir, touched
                )
            for node, count in per_node_cfg.items():
                hp_path = (
                    f"/sys/devices/system/node/{node}/"
                    f"hugepages/hugepages-{size_kb_int}kB"
                )
                node_dir = Path(hp_path)
                if node_dir.exists():
                    _write_text(
                        node_dir / "nr_hugepages",
                        str(count),
                        backup_dir,
                        touched,
                    )

    return ActionResult(
        name="memory",
        ok=True,
        detail="; ".join(details) or "no changes",
        touched_files=touched,
    )


def _apply_sysctl(
    cfg: Dict, backup_dir: Path, plan_only: bool
) -> ActionResult:
    lines = _sysctl_lines(cfg)
    touched: List[Path] = []
    if not lines:
        return ActionResult(
            name="sysctl",
            ok=True,
            detail="no sysctl entries",
            touched_files=touched,
        )
    if not plan_only:
        _write_text(SYSCTL_PATH, "\n".join(lines) + "\n", backup_dir, touched)
        run_cmd(["sysctl", "-p", str(SYSCTL_PATH)])
    return ActionResult(
        name="sysctl",
        ok=True,
        detail=f"{
            len(lines)} entries",
        touched_files=touched,
    )


def _apply_cpu(cfg: Dict, backup_dir: Path, plan_only: bool) -> ActionResult:
    cpu_cfg = cfg.get("cpu", {}) or {}
    governor = cpu_cfg.get("governor", {}).get("target")
    turbo = cpu_cfg.get("turbo")
    cstate_limit = cpu_cfg.get("cstate_limit")
    epp = cpu_cfg.get("epp")  # Energy Performance Preference
    touched: List[Path] = []
    details: List[str] = []

    cpu_root = Path("/sys/devices/system/cpu")

    # Set CPU governor
    for gov_path in cpu_root.glob("cpu[0-9]*/cpufreq/scaling_governor"):
        if governor:
            details.append(f"{gov_path.parent.name} -> {governor}")
            if not plan_only:
                _write_text(gov_path, str(governor), backup_dir, touched)

    # Turbo boost control
    if turbo is not None:
        no_turbo = Path("/sys/devices/system/cpu/intel_pstate/no_turbo")
        if no_turbo.exists():
            details.append(f"turbo {'enable' if turbo else 'disable'}")
            if not plan_only:
                _write_text(
                    no_turbo, "0" if turbo else "1", backup_dir, touched
                )

    # C-state limit (intel_idle max_cstate)
    if cstate_limit is not None:
        max_cstate = Path("/sys/module/intel_idle/parameters/max_cstate")
        if max_cstate.exists():
            details.append(f"max_cstate -> {cstate_limit}")
            if not plan_only:
                _write_text(max_cstate, str(cstate_limit), backup_dir, touched)
        else:
            # Try ACPI idle driver
            acpi_max_cstate = Path(
                "/sys/module/processor/parameters/max_cstate"
            )
            if acpi_max_cstate.exists():
                details.append(f"acpi max_cstate -> {cstate_limit}")
                if not plan_only:
                    _write_text(
                        acpi_max_cstate, str(cstate_limit), backup_dir, touched
                    )

    # Energy Performance Preference (EPP)
    if epp is not None:
        # Valid values: performance, balance_performance, balance_power, power
        epp_valid = {
            "performance",
            "balance_performance",
            "balance_power",
            "power",
        }
        if str(epp) in epp_valid:
            for epp_path in cpu_root.glob(
                "cpu[0-9]*/cpufreq/energy_performance_preference"
            ):
                details.append(f"{epp_path.parent.parent.name}: epp -> {epp}")
                if not plan_only:
                    _write_text(epp_path, str(epp), backup_dir, touched)
        else:
            details.append(f"invalid EPP value: {epp} (valid: {epp_valid})")

    return ActionResult(
        name="cpu",
        ok=True,
        detail="; ".join(details) or "no changes",
        touched_files=touched,
    )


def _apply_power(cfg: Dict, backup_dir: Path, plan_only: bool) -> ActionResult:
    """Apply power management settings for low latency.

    This handles settings that may require module parameters or other
    system-level changes beyond what _apply_cpu handles.
    """
    cpu_cfg = cfg.get("cpu", {}) or {}
    touched: List[Path] = []
    details: List[str] = []

    # Disable CPU frequency boost if requested (AMD)
    turbo = cpu_cfg.get("turbo")
    if turbo is not None:
        # AMD boost control
        amd_boost = Path("/sys/devices/system/cpu/cpufreq/boost")
        if amd_boost.exists():
            details.append(f"amd_boost -> {'1' if turbo else '0'}")
            if not plan_only:
                _write_text(
                    amd_boost, "1" if turbo else "0", backup_dir, touched
                )

    # C-state disable via cpuidle (per-state control)
    cstate_disable = cpu_cfg.get("cstate_disable_deeper_than")
    if cstate_disable is not None:
        try:
            disable_threshold = int(cstate_disable)
            cpuidle_root = Path("/sys/devices/system/cpu")
            for cpu_dir in cpuidle_root.glob("cpu[0-9]*"):
                cpuidle_dir = cpu_dir / "cpuidle"
                if not cpuidle_dir.exists():
                    continue
                for state_dir in cpuidle_dir.glob("state[0-9]*"):
                    state_num = int(state_dir.name.replace("state", ""))
                    disable_path = state_dir / "disable"
                    if disable_path.exists() and state_num > disable_threshold:
                        details.append(
                            f"{cpu_dir.name}/{state_dir.name}: disable"
                        )
                        if not plan_only:
                            _write_text(disable_path, "1", backup_dir, touched)
        except (ValueError, OSError) as exc:
            details.append(f"cstate_disable error: {exc}")

    # Intel uncore frequency scaling
    uncore_min = cpu_cfg.get("uncore_min_freq_khz")
    if uncore_min is not None:
        uncore_path = Path("/sys/devices/system/cpu/intel_uncore_frequency")
        if uncore_path.exists():
            for pkg_dir in uncore_path.glob("package_*"):
                min_path = pkg_dir / "min_freq_khz"
                if min_path.exists():
                    details.append(
                        f"{pkg_dir.name}: uncore_min -> {uncore_min}"
                    )
                    if not plan_only:
                        _write_text(
                            min_path, str(uncore_min), backup_dir, touched
                        )

    return ActionResult(
        name="power",
        ok=True,
        detail="; ".join(details) or "no changes",
        touched_files=touched,
    )


def _apply_irq(cfg: Dict, backup_dir: Path, plan_only: bool) -> ActionResult:
    irq_cfg = cfg.get("irq", {}) or {}
    manual = irq_cfg.get("manual_affinity") or []
    try:
        avoid = parse_cpulist(str(irq_cfg.get("avoid_cores_for_irqs", "") or ""))
    except ValueError as e:
        logger.warning("Invalid avoid_cores_for_irqs: %s", e)
        avoid = []
    touched: List[Path] = []
    details: List[str] = []

    if not manual:
        return ActionResult(
            name="irq",
            ok=True,
            detail="no affinity rules",
            touched_files=touched,
        )

    interrupts = Path("/proc/interrupts")
    if not interrupts.exists():
        return ActionResult(
            name="irq",
            ok=False,
            detail="/proc/interrupts missing",
            touched_files=touched,
        )

    lines = interrupts.read_text().splitlines()
    parsed_irqs: List[Tuple[int, str]] = []
    for line in lines[1:]:
        stripped = line.lstrip()
        if not stripped or not stripped[0].isdigit():
            continue
        irq_str, _, rest = stripped.partition(":")
        try:
            irq_num = int(irq_str.strip())
        except ValueError:
            continue
        rest_parts = rest.split()
        if not rest_parts:
            continue
        # Best-effort: match on the final token (e.g., ens3f0-TxRx-0).
        parsed_irqs.append((irq_num, rest_parts[-1]))

    for rule in manual:
        pattern = rule.get("match", "")
        cpus_raw = rule.get("cpus", [])
        cpus: List[int] = []
        if isinstance(cpus_raw, str):
            try:
                cpus = parse_cpulist(cpus_raw)
            except ValueError as e:
                logger.warning("Invalid CPU list in IRQ rule: %s", e)
                continue
        elif isinstance(cpus_raw, list):
            for c in cpus_raw:
                try:
                    cpus.append(int(c))
                except ValueError:
                    continue
        if avoid:
            cpus = [c for c in cpus if c not in avoid]
        if not cpus:
            logger.warning(
                "IRQ rule %r produces empty CPU set after filtering; skipping",
                pattern,
            )
            continue
        cpulist = ",".join(str(c) for c in sorted(set(cpus)))
        for irq_num, desc in parsed_irqs:
            if fnmatch.fnmatch(desc, pattern):
                details.append(f"irq {irq_num}->{cpulist}")
                if not plan_only:
                    path = Path(f"/proc/irq/{irq_num}/smp_affinity_list")
                    if path.exists():
                        _write_text(path, cpulist, backup_dir, touched)
    return ActionResult(
        name="irq",
        ok=True,
        detail="; ".join(details) or "no changes",
        touched_files=touched,
    )


def _apply_rps_rfs(
    cfg: Dict, snapshot: Dict, backup_dir: Path, plan_only: bool
) -> ActionResult:
    """Disable RPS/RFS on configured interfaces to reduce cross-CPU wakeups.

    Returns details of changes made and logs any failures.
    """
    irq_cfg = cfg.get("irq", {}) or {}
    disable_rps = irq_cfg.get("disable_rps", False)
    disable_rfs = irq_cfg.get("disable_rfs", False)

    net_cfg = cfg.get("network", {}) or {}
    interfaces = [
        i.get("name") for i in net_cfg.get("interfaces", []) if i.get("name")
    ]
    if not interfaces:
        # Use all NICs from snapshot if none specified
        interfaces = [
            n.get("name") for n in snapshot.get("nics", []) if n.get("name")
        ]

    touched: List[Path] = []
    details: List[str] = []
    warnings: List[str] = []

    if not (disable_rps or disable_rfs):
        return ActionResult(
            name="rps_rfs",
            ok=True,
            detail="RPS/RFS disable not configured",
            touched_files=touched,
        )

    if disable_rfs:
        # RFS is controlled via a global knob.
        rfs_global = Path("/proc/sys/net/core/rps_sock_flow_entries")
        if rfs_global.exists():
            details.append("global: rps_sock_flow_entries=0")
            if not plan_only:
                try:
                    rfs_global.write_text("0\n")
                except OSError as e:
                    msg = f"Failed to disable RFS globally: {e}"
                    logger.warning(msg)
                    warnings.append(msg)

    for nic in interfaces:
        queues_dir = Path(f"/sys/class/net/{nic}/queues")
        if not queues_dir.exists():
            logger.debug("Queues directory not found for %s", nic)
            continue

        if disable_rps:
            # Disable RPS by setting rps_cpus to 0 for all RX queues
            for rxq in queues_dir.glob("rx-*"):
                rps_path = rxq / "rps_cpus"
                if rps_path.exists():
                    details.append(f"{nic}/{rxq.name}: rps_cpus=0")
                    if not plan_only:
                        try:
                            rps_path.write_text("0\n")
                        except OSError as e:
                            msg = f"Failed to disable RPS on {nic}/{rxq.name}: {e}"
                            logger.warning(msg)
                            warnings.append(msg)
                # Also set rps_flow_cnt to 0
                rfc_path = rxq / "rps_flow_cnt"
                if rfc_path.exists():
                    details.append(f"{nic}/{rxq.name}: rps_flow_cnt=0")
                    if not plan_only:
                        try:
                            rfc_path.write_text("0\n")
                        except OSError as e:
                            msg = f"Failed to set rps_flow_cnt on {nic}/{rxq.name}: {e}"
                            logger.warning(msg)
                            warnings.append(msg)

    # Include warnings in detail if any occurred
    detail_str = "; ".join(details) or "no changes"
    if warnings:
        detail_str += f" (warnings: {len(warnings)})"

    return ActionResult(
        name="rps_rfs",
        ok=True,
        detail=detail_str,
        touched_files=touched,
    )


def _apply_nic(cfg: Dict, backup_dir: Path, plan_only: bool) -> ActionResult:
    net_cfg = cfg.get("network", {}) or {}
    defaults = net_cfg.get("defaults", {}) or {}
    interfaces = net_cfg.get("interfaces", []) or []
    nic_names = [i.get("name") for i in interfaces if i.get("name")]
    touched: List[Path] = []
    details: List[str] = []

    offload_flags = []
    for key, flag in (
        ("disable_gro", "gro"),
        ("disable_lro", "lro"),
        ("disable_tso", "tso"),
        ("disable_gso", "gso"),
    ):
        if defaults.get(key) is True:
            offload_flags.append(flag)

    if not nic_names and net_cfg.get("interfaces") == []:
        # if none specified, skip silently
        return ActionResult(
            name="nic",
            ok=True,
            detail="no NICs provided",
            touched_files=touched,
        )

    def _maybe_run(cmd: List[str]):
        if not plan_only:
            run_cmd(cmd)

    for entry in interfaces:
        nic = entry.get("name")
        if not nic:
            continue
        if offload_flags:
            details.append(f"{nic}: offloads off ({', '.join(offload_flags)})")
            offload_args: List[str] = []
            for flag in offload_flags:
                offload_args.extend([flag, "off"])
            _maybe_run(
                ["ethtool", "-K", nic, *offload_args]
            )

        coalesce = entry.get("coalescing", {}) or {}
        coal_args: List[str] = []
        key_map = {
            "rx_usecs": "rx-usecs",
            "tx_usecs": "tx-usecs",
            "rx_frames": "rx-frames",
            "tx_frames": "tx-frames",
        }
        for key, ethtool_key in key_map.items():
            if key in coalesce:
                coal_args.extend([ethtool_key, str(coalesce[key])])
        if coal_args:
            details.append(f"{nic}: coalescing {' '.join(coal_args)}")
            _maybe_run(["ethtool", "-C", nic, *coal_args])

        rings = entry.get("rings", {}) or {}
        ring_args: List[str] = []
        for key in ("rx", "tx"):
            if key in rings:
                ring_args.extend([key, str(rings[key])])
        if ring_args:
            details.append(f"{nic}: rings {' '.join(ring_args)}")
            _maybe_run(["ethtool", "-G", nic, *ring_args])

        flow = entry.get("flow_control", {}) or {}
        flow_args: List[str] = []
        for key in ("rx", "tx"):
            if key in flow:
                flow_args.extend([key, "on" if flow[key] else "off"])
        if flow_args:
            details.append(f"{nic}: flow {' '.join(flow_args)}")
            _maybe_run(["ethtool", "-A", nic, *flow_args])

        queues = entry.get("queues", {}) or {}
        queue_args: List[str] = []
        for key in ("combined", "rx", "tx"):
            if key in queues:
                queue_args.extend([key, str(queues[key])])
        if queue_args:
            details.append(f"{nic}: queues {' '.join(queue_args)}")
            _maybe_run(["ethtool", "-L", nic, *queue_args])

    return ActionResult(
        name="nic",
        ok=True,
        detail="; ".join(details) or "no changes",
        touched_files=touched,
    )


def _merge_cmdline(existing: Dict[str, str], desired: Dict[str, str]) -> str:
    merged = dict(existing)
    merged.update({k: v for k, v in desired.items() if v is not None})
    parts = []
    for k, v in merged.items():
        if v == "":
            parts.append(k)
        else:
            parts.append(f"{k}={v}")
    return " ".join(parts)


def _apply_kernel(
    cfg: Dict, backup_dir: Path, plan_only: bool
) -> ActionResult:
    kernel_cfg = cfg.get("kernel", {}) or {}
    cmd_cfg = kernel_cfg.get("cmdline", {}) or {}
    safety = cfg.get("safety", {}) or {}
    allow_grub = safety.get("allow_grub_edit", False)
    allow_mitigations = safety.get("allow_dangerous_mitigations", False)
    touched: List[Path] = []
    if not cmd_cfg:
        return ActionResult(
            name="kernel",
            ok=True,
            detail="no kernel cmdline changes",
            touched_files=touched,
        )
    current_cmdline = parse_cmdline()
    if not allow_grub:
        return ActionResult(
            name="kernel",
            ok=True,
            detail="skipped kernel cmdline (allow_grub_edit=false)",
            touched_files=touched,
        )

    todo_keys = [
        k
        for k, v in cmd_cfg.items()
        if isinstance(v, str) and "TODO" in v.upper()
    ]
    if todo_keys:
        return ActionResult(
            name="kernel",
            ok=False,
            detail=f"kernel cmdline contains TODO placeholders: {todo_keys}",
            touched_files=touched,
        )

    mitigations = cmd_cfg.get("mitigations")
    if (
        isinstance(mitigations, str)
        and mitigations.lower() == "off"
        and not allow_mitigations
    ):
        return ActionResult(
            name="kernel",
            ok=False,
            detail="mitigations=off requires safety.allow_dangerous_mitigations=true",
            touched_files=touched,
        )

    merged_line = _merge_cmdline(current_cmdline, cmd_cfg)
    reboot_required = False
    if not plan_only:
        _backup_file(GRUB_DEFAULT, backup_dir, touched)
        try:
            lines = GRUB_DEFAULT.read_text().splitlines()
        except FileNotFoundError:
            lines = []
        except OSError as e:
            logger.warning("Could not read %s: %s", GRUB_DEFAULT, e)
            lines = []

        updated = []
        found = False
        for line in lines:
            if line.startswith("GRUB_CMDLINE_LINUX"):
                updated.append(f'GRUB_CMDLINE_LINUX="{merged_line}"')
                found = True
            else:
                updated.append(line)
        if not found:
            updated.append(f'GRUB_CMDLINE_LINUX="{merged_line}"')
        GRUB_DEFAULT.parent.mkdir(parents=True, exist_ok=True)
        GRUB_DEFAULT.write_text("\n".join(updated) + "\n")
        reboot_required = True

        # Regenerate GRUB config for BIOS
        if GRUB_CFG_BIOS.exists():
            result = run_cmd(["grub2-mkconfig", "-o", str(GRUB_CFG_BIOS)])
            if not result.ok:
                logger.warning("grub2-mkconfig for BIOS failed: %s", result.stderr)

        # Regenerate GRUB config for EFI (with dynamic path detection)
        efi_grub = detect_efi_grub_path()
        if efi_grub:
            result = run_cmd(["grub2-mkconfig", "-o", str(efi_grub)])
            if not result.ok:
                logger.warning("grub2-mkconfig for EFI failed: %s", result.stderr)

    return ActionResult(
        name="kernel",
        ok=True,
        detail="GRUB_CMDLINE_LINUX merged",
        reboot_required=reboot_required,
        touched_files=touched,
    )


def _apply_time_sync(
    cfg: Dict, snapshot: Dict, plan_only: bool
) -> ActionResult:
    ts_cfg = cfg.get("time_sync", {}) or {}
    ptp_cfg = ts_cfg.get("ptp", {}) or {}
    iface = ptp_cfg.get("interface")
    if iface:
        nic_names = [
            n.get("name") for n in snapshot.get("nics", []) if n.get("name")
        ]
        if iface not in nic_names:
            return ActionResult(
                name="time",
                ok=False,
                detail=f"PTP interface {iface} not found",
                touched_files=[],
            )
    # No heavy changes; only validation here.
    return ActionResult(
        name="time",
        ok=True,
        detail="validated time sync settings",
        touched_files=[],
    )


def _apply_user_stacks(
    cfg: Dict, backup_dir: Path, plan_only: bool
) -> ActionResult:
    generated_dir = backup_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    details: List[str] = []
    for section in ("onload", "vma", "rdma"):
        if section in cfg:
            details.append(f"generated {section} env skeleton")
            if not plan_only:
                (generated_dir / f"{section}.env").write_text(
                    "# TODO: populate application stack settings\n"
                )
    return ActionResult(
        name="onload/vma/rdma",
        ok=True,
        detail="; ".join(details) or "no changes",
        touched_files=[],
    )


def apply_config(
    cfg: Dict, plan_only: bool = False, backup_root: Optional[Path] = None
) -> ApplyResult:
    plan, errors = plan_apply(cfg, backup_root=backup_root)
    if errors:
        return ApplyResult(
            ok=False,
            backup_dir=plan.backup_dir,
            actions=[],
            errors=errors,
            reboot_required=False,
            persistence=plan.persistence,
        )

    results: List[ActionResult] = []
    touched: List[Path] = []
    reboot_required = False
    try:
        for func in [
            lambda: _apply_services(cfg, plan.backup_dir, plan_only),
            lambda: _apply_memory(
                cfg, plan.snapshot, plan.backup_dir, plan_only
            ),
            lambda: _apply_sysctl(cfg, plan.backup_dir, plan_only),
            lambda: _apply_cpu(cfg, plan.backup_dir, plan_only),
            lambda: _apply_power(cfg, plan.backup_dir, plan_only),
            lambda: _apply_irq(cfg, plan.backup_dir, plan_only),
            lambda: _apply_rps_rfs(
                cfg, plan.snapshot, plan.backup_dir, plan_only
            ),
            lambda: _apply_nic(cfg, plan.backup_dir, plan_only),
            lambda: _apply_kernel(cfg, plan.backup_dir, plan_only),
            lambda: _apply_time_sync(cfg, plan.snapshot, plan_only),
            lambda: _apply_user_stacks(cfg, plan.backup_dir, plan_only),
        ]:
            res = func()
            results.append(res)
            reboot_required = reboot_required or res.reboot_required
            touched.extend(res.touched_files)
            if not res.ok:
                raise RuntimeError(res.detail)
    except Exception as exc:  # noqa: BLE001
        if not plan_only:
            _restore_files(touched, plan.backup_dir)
        return ApplyResult(
            ok=False,
            backup_dir=plan.backup_dir,
            actions=results,
            errors=[str(exc)],
            reboot_required=reboot_required,
            persistence=plan.persistence,
        )

    return ApplyResult(
        ok=True,
        backup_dir=plan.backup_dir,
        actions=results,
        errors=[],
        reboot_required=reboot_required,
        persistence=plan.persistence,
    )
