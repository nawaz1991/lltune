# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Config model and validation for LLTune."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml

from .utils import parse_cpulist

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


@dataclass
class Issue:
    severity: str  # info/warning/error
    field: str
    message: str


@dataclass
class AuditResult:
    issues: List[Issue] = field(default_factory=list)

    def add(self, severity: str, field: str, message: str):
        self.issues.append(
            Issue(severity=severity, field=field, message=message)
        )

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)


def load_config(path: Path) -> Dict:
    """Load YAML config into a dict."""
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping")
    return data


ALLOWED_TOP_LEVEL = {
    "version",
    "metadata",
    "hardware",
    "cpu",
    "kernel",
    "memory",
    "network",
    "irq",
    "time_sync",
    "services",
    "safety",
    "onload",
    "vma",
    "rdma",
    "recommendations",
}


def _check_todo_values(cfg: Dict, res: AuditResult, path: str = "") -> None:
    """Recursively check for TODO placeholder values and emit warnings.

    Args:
        cfg: Config dict or value to check
        res: AuditResult to add warnings to
        path: Current path in config for error messages
    """
    if isinstance(cfg, dict):
        for key, value in cfg.items():
            new_path = f"{path}.{key}" if path else key
            _check_todo_values(value, res, new_path)
    elif isinstance(cfg, list):
        for i, item in enumerate(cfg):
            _check_todo_values(item, res, f"{path}[{i}]")
    elif isinstance(cfg, str) and "TODO" in cfg:
        res.add(
            "warning",
            path,
            f"Contains TODO placeholder: {cfg!r} - replace before applying"
        )


def validate_schema(cfg: Dict) -> AuditResult:
    """Validate config schema and check for TODO placeholders."""
    res = AuditResult()

    # Check for TODO placeholders throughout config
    _check_todo_values(cfg, res)

    for key in cfg.keys():
        if key not in ALLOWED_TOP_LEVEL:
            res.add("error", key, "Unknown top-level key")
    version = cfg.get("version")
    if version is None:
        res.add("error", "version", "Missing config version")
    elif version != SCHEMA_VERSION:
        res.add(
            "error",
            "version",
            f"Incompatible config version {version}; expected {SCHEMA_VERSION}",
        )
    safety = cfg.get("safety", {}) or {}
    for key in ("allow_grub_edit", "allow_dangerous_mitigations"):
        if key in safety and not isinstance(safety[key], bool):
            res.add("error", f"safety.{key}", "Must be boolean")

    # If GRUB edits are explicitly enabled, require kernel cmdline values
    # to be concrete (no TODO placeholders), and gate dangerous flags.
    allow_grub_edit = safety.get("allow_grub_edit", False)
    allow_dangerous_mitigations = safety.get(
        "allow_dangerous_mitigations", False
    )
    kernel_cfg = cfg.get("kernel", {}) or {}
    cmdline = kernel_cfg.get("cmdline", {}) or {}
    if cmdline and allow_grub_edit:
        if not isinstance(cmdline, dict):
            res.add("error", "kernel.cmdline", "Must be a mapping")
        else:
            todo_keys = [
                k
                for k, v in cmdline.items()
                if isinstance(v, str) and "TODO" in v.upper()
            ]
            if todo_keys:
                res.add(
                    "error",
                    "kernel.cmdline",
                    f"Kernel cmdline contains TODO placeholders: {todo_keys}",
                )
            mitigations = cmdline.get("mitigations")
            if (
                isinstance(mitigations, str)
                and mitigations.lower() == "off"
                and not allow_dangerous_mitigations
            ):
                res.add(
                    "error",
                    "kernel.cmdline.mitigations",
                    "mitigations=off requires safety.allow_dangerous_mitigations=true",
                )
    services = cfg.get("services", {}) or {}
    if "irqbalance" in services and not isinstance(
        services["irqbalance"], bool
    ):
        res.add("error", "services.irqbalance", "Must be boolean")
    if (
        "tuned" in services
        and services["tuned"] is not None
        and not isinstance(services["tuned"], str)
    ):
        res.add("error", "services.tuned", "Must be string or null")
    return res


def _validate_cpu(cfg: Dict, res: AuditResult, snapshot_cpus: List[int]):
    """Validate CPU configuration against available CPUs."""
    cpu_cfg = cfg.get("cpu", {}) or {}
    iso = cpu_cfg.get("isolate_cores")
    if iso:
        try:
            parsed = parse_cpulist(str(iso))
            bad = [c for c in parsed if c not in snapshot_cpus]
            if bad:
                res.add("error", "cpu.isolate_cores", f"Invalid CPU IDs: {bad}")
        except ValueError as e:
            res.add("error", "cpu.isolate_cores", f"Invalid CPU list format: {e}")


def _validate_memory(cfg: Dict, res: AuditResult, total_kb: Optional[int]):
    mem_cfg = cfg.get("memory", {}) or {}
    hugepages = mem_cfg.get("hugepages", {})
    total_hp = hugepages.get("total")
    size_kb = hugepages.get("size_kb", 2048)  # Default to 2MB pages
    if total_hp and total_kb:
        try:
            hp_int = int(total_hp)
            try:
                size_kb_int = int(size_kb)
            except (ValueError, TypeError):
                size_kb_int = 2048
            hp_kb = hp_int * size_kb_int
            # Leave some reserve (10% or 1GB minimum) for OS
            reserve_kb = max(total_kb // 10, 1024 * 1024)
            available_kb = total_kb - reserve_kb
            if hp_kb > available_kb:
                res.add(
                    "error",
                    "memory.hugepages.total",
                    f"Hugepages ({
                        hp_kb //
                        1024} MB) exceed available memory ({
                        available_kb //
                        1024} MB after OS reserve)",
                )
        except ValueError:
            res.add(
                "warning",
                "memory.hugepages.total",
                "Hugepages total should be integer; set TODO to a number",
            )


def _validate_network(cfg: Dict, res: AuditResult, nic_names: List[str]):
    net = cfg.get("network", {}) or {}
    for entry in net.get("interfaces", []) or []:
        name = entry.get("name")
        if name and name not in nic_names:
            res.add(
                "error",
                f"network.interfaces.{name}",
                "NIC not found on system",
            )


def _validate_numa(cfg: Dict, res: AuditResult, numa_nodes: Set[int]):
    mem_cfg = cfg.get("memory", {}) or {}
    hp_cfg = mem_cfg.get("hugepages", {}) or {}
    per_node = hp_cfg.get("per_node", {}) or {}
    if not isinstance(per_node, dict):
        res.add(
            "warning",
            "memory.hugepages.per_node",
            "Expected mapping of node->count",
        )
        return
    for node in per_node.keys():
        try:
            node_id = int(str(node).replace("node", ""))
        except ValueError:
            res.add(
                "error",
                f"memory.hugepages.per_node.{node}",
                "Invalid NUMA node format",
            )
            continue
        if node_id not in numa_nodes:
            res.add(
                "error",
                f"memory.hugepages.per_node.{node}",
                "NUMA node does not exist",
            )


def _validate_kernel(cfg: Dict, res: AuditResult):
    kernel_cfg = cfg.get("kernel", {}) or {}
    cmdline = kernel_cfg.get("cmdline", {}) or {}
    dangerous = {"noapic", "nolapic", "nosmp"}
    for key in cmdline.keys():
        if key in dangerous:
            res.add(
                "error",
                f"kernel.cmdline.{key}",
                "Dangerous kernel flag not allowed",
            )

    # Cross-validate isolcpus/nohz_full/rcu_nocbs consistency
    isolcpus = cmdline.get("isolcpus", "")
    nohz_full = cmdline.get("nohz_full", "")
    rcu_nocbs = cmdline.get("rcu_nocbs", "")

    # If any are specified, all should match (or at least nohz_full/rcu_nocbs
    # should be subset of isolcpus)
    if isolcpus and not isinstance(isolcpus, str):
        isolcpus = ""
    if nohz_full and not isinstance(nohz_full, str):
        nohz_full = ""
    if rcu_nocbs and not isinstance(rcu_nocbs, str):
        rcu_nocbs = ""

    # Skip TODO placeholders
    if isolcpus and "TODO" not in str(isolcpus):
        try:
            iso_cpus = set(parse_cpulist(str(isolcpus)))
        except ValueError as e:
            res.add("error", "kernel.cmdline.isolcpus", f"Invalid format: {e}")
            return

        if nohz_full and "TODO" not in str(nohz_full):
            try:
                nohz_cpus = set(parse_cpulist(str(nohz_full)))
                if nohz_cpus and not nohz_cpus.issubset(iso_cpus):
                    extra = nohz_cpus - iso_cpus
                    res.add(
                        "warning",
                        "kernel.cmdline.nohz_full",
                        f"CPUs {extra} in nohz_full but not in isolcpus",
                    )
            except ValueError as e:
                res.add("error", "kernel.cmdline.nohz_full", f"Invalid format: {e}")

        if rcu_nocbs and "TODO" not in str(rcu_nocbs):
            try:
                rcu_cpus = set(parse_cpulist(str(rcu_nocbs)))
                if rcu_cpus and not rcu_cpus.issubset(iso_cpus):
                    extra = rcu_cpus - iso_cpus
                    res.add(
                        "warning",
                        "kernel.cmdline.rcu_nocbs",
                        f"CPUs {extra} in rcu_nocbs but not in isolcpus",
                    )
            except ValueError as e:
                res.add("error", "kernel.cmdline.rcu_nocbs", f"Invalid format: {e}")


def _validate_cpu_config(cfg: Dict, res: AuditResult):
    """Validate CPU configuration fields."""
    cpu_cfg = cfg.get("cpu", {}) or {}
    governor = cpu_cfg.get("governor", {}) or {}
    target = governor.get("target")
    if target:
        allowed_governors = {
            "performance",
            "powersave",
            "schedutil",
            "ondemand",
            "conservative",
            "userspace",
        }
        if target not in allowed_governors:
            res.add(
                "error",
                "cpu.governor.target",
                f"Invalid governor '{target}'; must be one of {allowed_governors}",
            )


def validate_cross(cfg: Dict, snapshot: Dict) -> AuditResult:
    res = AuditResult()
    # Convert CPU IDs from string keys (from JSON) to integers
    cpu_ids = [
        int(k)
        for k in (snapshot.get("cpu", {}).get("per_cpu_governor") or {}).keys()
    ]
    _validate_cpu(cfg, res, cpu_ids)
    # Validate governor enum and other CPU fields
    _validate_cpu_config(cfg, res)
    total_kb = snapshot.get("memory", {}).get("total_kb")
    _validate_memory(cfg, res, total_kb)
    nic_names = [
        n.get("name") for n in snapshot.get("nics", []) if n.get("name")
    ]
    _validate_network(cfg, res, nic_names)
    numa_nodes = {
        n.get("node_id")
        for n in snapshot.get("numa", {}).get("nodes", [])
        if "node_id" in n
    }
    _validate_numa(cfg, res, numa_nodes)
    _validate_kernel(cfg, res)
    rdma_cfg = cfg.get("rdma", {}) or {}
    rdma_devices = [
        d.get("name") or d.get("device")
        for d in snapshot.get("rdma", {}).get("devices", [])
    ]
    for dev in rdma_cfg.get("devices", []) or []:
        if dev not in rdma_devices:
            res.add(
                "error",
                f"rdma.devices.{dev}",
                "RDMA device not present on system",
            )
    return res
