# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Configuration generation from snapshot and recommendations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence, Union

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .env import OSInfo
from .models import (
    CpuInfo,
    MemoryInfo,
    NicInfo,
    NicQueues,
    Snapshot,
)
from .recommendations import Recommendation
from .version import __version__

yaml = YAML()
yaml.indent(mapping=2, sequence=4, offset=2)


def _commented_map(**kwargs) -> CommentedMap:
    return CommentedMap(**kwargs)


def hydrate_snapshot(data: dict) -> Snapshot:
    """Build a Snapshot object from a dict (best effort)."""
    snap = Snapshot()
    host = data.get("host", {})
    snap.host.hostname = host.get("hostname", snap.host.hostname)
    snap.host.kernel = host.get("kernel", snap.host.kernel)
    os_data = host.get("os") or {}
    if os_data:
        snap.host.os = OSInfo(
            os_id=os_data.get("os_id", ""),
            version_id=os_data.get("version_id", ""),
            name=os_data.get("name", ""),
        )
    # Use __dataclass_fields__ to correctly check valid fields for dataclasses
    cpu_fields = CpuInfo.__dataclass_fields__
    snap.cpu = CpuInfo(
        **{k: v for k, v in data.get("cpu", {}).items() if k in cpu_fields}
    )
    memory_fields = MemoryInfo.__dataclass_fields__
    snap.memory = MemoryInfo(
        **{
            k: v
            for k, v in data.get("memory", {}).items()
            if k in memory_fields
        }
    )
    snap.nics = []
    nic_fields = NicInfo.__dataclass_fields__
    queues_fields = NicQueues.__dataclass_fields__
    for nic in data.get("nics", []):
        nic_data = {k: v for k, v in nic.items() if k in nic_fields}
        # Handle nested queues object
        if "queues" in nic and isinstance(nic["queues"], dict):
            nic_data["queues"] = NicQueues(
                **{
                    k: v
                    for k, v in nic["queues"].items()
                    if k in queues_fields
                }
            )
        snap.nics.append(NicInfo(**nic_data))
    return snap


def generate_config_dict(
    snapshot: Union[Snapshot, dict],
    recommendations: Optional[Sequence[Recommendation]] = None,
) -> CommentedMap:
    snap = (
        snapshot
        if isinstance(snapshot, Snapshot)
        else hydrate_snapshot(snapshot)
    )
    recs = recommendations or []
    cfg = _commented_map()
    cfg["version"] = 1
    cfg["metadata"] = _commented_map(
        generated_at=datetime.now(timezone.utc).isoformat(),
        host=snap.host.hostname,
        kernel=snap.host.kernel,
        tool_version=__version__,
    )
    hw = _commented_map()
    hw["sockets"] = snap.cpu.sockets
    hw["cores_per_socket"] = snap.cpu.cores_per_socket
    hw["threads_per_core"] = snap.cpu.threads_per_core
    hw["numa_nodes"] = len(getattr(snap.numa, "nodes", []))
    hw["nics"] = CommentedSeq([nic.name for nic in snap.nics])
    cfg["hardware"] = hw

    cpu = _commented_map()
    cpu["governor"] = _commented_map(target="performance")
    cpu.yaml_set_comment_before_after_key(
        "governor", before="Target CPU governor for all cores."
    )
    cpu["isolate_cores"] = "TODO: e.g., 2-7,10-15"
    cfg["cpu"] = cpu

    kernel = _commented_map()
    cmdline = _commented_map()
    cmdline["isolcpus"] = (
        "TODO: match isolate_cores (e.g., managed_irq,domain,2-7)"
    )
    cmdline["nohz_full"] = "TODO: match isolate_cores"
    cmdline["rcu_nocbs"] = "TODO: match isolate_cores"
    cmdline["skew_tick"] = "1"  # Reduces jitter from timer tick alignment
    cmdline["tsc"] = "reliable"  # Mark TSC as reliable for timekeeping
    # Disable soft lockup detector on isolated cores
    cmdline["nosoftlockup"] = ""
    cmdline["nmi_watchdog"] = "0"  # Disable NMI watchdog
    cmdline["nowatchdog"] = ""  # Disable watchdog
    cmdline["transparent_hugepage"] = "never"  # Ensure THP disabled at boot
    # Use acpi-cpufreq for better control (Intel)
    cmdline["intel_pstate"] = "disable"
    cmdline["processor.max_cstate"] = "1"  # Limit C-states at boot
    # Ultra-low latency: spin instead of halt (WARNING: 100% CPU)
    cmdline["idle"] = "poll"
    cmdline.yaml_set_comment_before_after_key(
        "idle",
        before="WARNING: idle=poll uses 100% CPU - remove if not needed",
    )
    # Disable CPU vulnerability mitigations (if risk accepted)
    cmdline["mitigations"] = "auto"
    cmdline.yaml_set_comment_before_after_key(
        "mitigations", before="Set only if security risk is accepted"
    )
    kernel["cmdline"] = cmdline
    cfg["kernel"] = kernel

    memory = _commented_map()
    memory["thp_runtime"] = "never"
    memory["swap_disable"] = bool(snap.memory.swap_devices)
    memory["numa_balancing"] = False
    memory["ksm"] = False
    memory["dirty_ratio"] = 10  # Reduce dirty page writeback latency
    memory["dirty_background_ratio"] = 5
    memory["stat_interval"] = 120  # Reduce VM statistics collection overhead
    # Determine default hugepage size from discovered hugepages
    hp_keys = list((snap.memory.hugepages or {}).keys())
    default_hp_size = "2048"  # Default to 2MB pages
    if hp_keys:
        # Try to extract size from keys like "2048kB" or "1048576kB"
        for key in hp_keys:
            if key.endswith("kB"):
                default_hp_size = key.replace("kB", "")
                break
    memory["hugepages"] = _commented_map(
        size_kb=default_hp_size,
        total="TODO: number of pages",
        per_node=_commented_map(
            **{
                f"node{node.node_id}": "TODO: pages"
                for node in getattr(getattr(snap, "numa", None), "nodes", [])
            }
        )
        or _commented_map(node0="TODO: pages"),
    )
    # Memory locking for trading applications
    memory["mlock"] = _commented_map(
        enabled=True,
        user="*",
        soft="unlimited",
        hard="unlimited",
        max_map_count=262144,
    )
    memory["limits"] = _commented_map(
        nofile=1048576,
        nproc=65536,
        rtprio=99,
    )
    cfg["memory"] = memory

    network = _commented_map()
    network["defaults"] = _commented_map(
        disable_gro=True, disable_lro=True, disable_tso=True, disable_gso=True
    )
    # Network sysctl tuning for low latency
    network["sysctl"] = _commented_map(
        rmem_max=67108864,  # 64MB
        wmem_max=67108864,
        rmem_default=67108864,
        wmem_default=67108864,
        tcp_rmem="4096 87380 67108864",
        tcp_wmem="4096 65536 67108864",
        tcp_timestamps=False,  # Disable for HFT (reduces overhead)
        tcp_sack=False,  # Disable for predictable latency
        tcp_low_latency=True,
        tcp_fastopen=3,
        tcp_tw_reuse=True,
        tcp_fin_timeout=15,
        busy_poll=50,  # Enable busy polling (critical for low latency)
        busy_read=50,
        netdev_max_backlog=250000,
        netdev_budget=600,
        somaxconn=65535,
        file_max=2097152,
    )
    network["interfaces"] = CommentedSeq(
        [
            _commented_map(name=nic.name, role="TODO: trading/control")
            for nic in snap.nics
        ]
    )
    cfg["network"] = network

    irq = _commented_map()
    irq["manual_affinity"] = CommentedSeq()
    irq.yaml_set_comment_before_after_key(
        "manual_affinity",
        before="List of {match: pattern, cpus: [ids]} entries to pin IRQs.",
    )
    irq["avoid_cores_for_irqs"] = "TODO: e.g., trading cores"
    cfg["irq"] = irq

    time_sync = _commented_map()
    time_sync["ntp"] = True
    time_sync["ptp"] = _commented_map(
        interface="TODO: ptp-capable nic", phc2sys=True
    )
    cfg["time_sync"] = time_sync

    services = _commented_map()
    services["irqbalance"] = False
    services["tuned"] = "latency-performance"
    cfg["services"] = services

    safety = _commented_map()
    safety["allow_grub_edit"] = False
    safety["allow_dangerous_mitigations"] = False
    cfg["safety"] = safety

    cfg["recommendations"] = [rec.to_dict() for rec in recs]
    return cfg


def dump_config_yaml(cfg: CommentedMap, path: Optional[Path] = None) -> str:
    """Render the commented config to YAML."""
    from io import StringIO

    buf = StringIO()
    yaml.dump(cfg, buf)
    text = buf.getvalue()
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return text
