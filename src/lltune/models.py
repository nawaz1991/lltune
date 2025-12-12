# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Dataclasses representing discovery snapshots and related entities."""

from __future__ import annotations

import socket
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .env import OSInfo


def _strip_none(obj):
    """Recursively remove None values from nested dict/list structures."""
    if isinstance(obj, dict):
        return {k: _strip_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_none(v) for v in obj if v is not None]
    return obj


@dataclass
class CpuInfo:
    vendor: Optional[str] = None
    model_name: Optional[str] = None
    family: Optional[str] = None
    model: Optional[str] = None
    sockets: int = 0
    cores_per_socket: int = 0
    threads_per_core: int = 0
    smt_enabled: Optional[bool] = None
    per_cpu_governor: Dict[int, str] = field(default_factory=dict)
    # e.g., {"min_khz": 1200000, "max_khz": 3800000}
    per_cpu_freq: Dict[int, Dict[str, int]] = field(default_factory=dict)
    cmdline_flags: Dict[str, str] = field(default_factory=dict)


@dataclass
class NumaNode:
    node_id: int
    cpus: List[int] = field(default_factory=list)
    mem_total_kb: Optional[int] = None
    mem_free_kb: Optional[int] = None


@dataclass
class NumaInfo:
    nodes: List[NumaNode] = field(default_factory=list)
    cpu_to_node: Dict[int, int] = field(default_factory=dict)


@dataclass
class MemoryInfo:
    total_kb: Optional[int] = None
    swap_devices: List[Dict[str, str]] = field(default_factory=list)
    thp_enabled: Optional[str] = None
    thp_defrag: Optional[str] = None
    # keyed by size (e.g., "2048kB") with totals/per-node
    hugepages: Dict[str, Dict[str, int]] = field(default_factory=dict)
    numa_balancing: Optional[bool] = None
    ksm_enabled: Optional[bool] = None


@dataclass
class SysctlInfo:
    """Current sysctl values for network and VM tuning."""

    # Network buffer sizes
    rmem_max: Optional[int] = None
    wmem_max: Optional[int] = None
    rmem_default: Optional[int] = None
    wmem_default: Optional[int] = None
    tcp_rmem: Optional[str] = None  # "min default max"
    tcp_wmem: Optional[str] = None  # "min default max"
    udp_rmem_min: Optional[int] = None
    udp_wmem_min: Optional[int] = None
    # Low latency TCP settings
    tcp_timestamps: Optional[int] = None
    tcp_sack: Optional[int] = None
    tcp_low_latency: Optional[int] = None
    tcp_fastopen: Optional[int] = None
    tcp_tw_reuse: Optional[int] = None
    tcp_fin_timeout: Optional[int] = None
    # Busy polling
    busy_poll: Optional[int] = None
    busy_read: Optional[int] = None
    # Backlog and queuing
    netdev_max_backlog: Optional[int] = None
    netdev_budget: Optional[int] = None
    somaxconn: Optional[int] = None
    # VM settings
    dirty_ratio: Optional[int] = None
    dirty_background_ratio: Optional[int] = None
    max_map_count: Optional[int] = None
    # File system
    file_max: Optional[int] = None


@dataclass
class LimitsInfo:
    """Current resource limits from /etc/security/limits.d/."""

    memlock_soft: Optional[str] = None  # "unlimited" or numeric
    memlock_hard: Optional[str] = None
    nofile_soft: Optional[int] = None
    nofile_hard: Optional[int] = None
    nproc_soft: Optional[int] = None
    nproc_hard: Optional[int] = None


@dataclass
class NicQueues:
    rx_queues: Optional[int] = None
    tx_queues: Optional[int] = None
    combined: Optional[int] = None
    rss: Optional[bool] = None
    xps: Dict[str, str] = field(default_factory=dict)
    rps: Dict[str, str] = field(default_factory=dict)
    rps_flow_cnt: Optional[int] = None


@dataclass
class NicInfo:
    name: str
    mac: Optional[str] = None
    mtu: Optional[int] = None
    link: Optional[str] = None
    speed_mbps: Optional[int] = None
    vendor: Optional[str] = None
    driver: Optional[str] = None
    driver_version: Optional[str] = None
    firmware_version: Optional[str] = None
    bus_info: Optional[str] = None
    numa_node: Optional[int] = None
    offloads: Dict[str, str] = field(default_factory=dict)
    coalescing: Dict[str, str] = field(default_factory=dict)
    rings: Dict[str, int] = field(default_factory=dict)
    flow_control: Dict[str, str] = field(default_factory=dict)
    queues: NicQueues = field(default_factory=NicQueues)


@dataclass
class RdmaInfo:
    devices: List[Dict[str, str]] = field(default_factory=list)
    associations: Dict[str, List[str]] = field(
        default_factory=dict
    )  # rdma dev -> list of netdevs


@dataclass
class IrqInfo:
    irq: int
    description: str
    affinity: List[int] = field(default_factory=list)
    counts: Dict[int, int] = field(default_factory=dict)
    rps_cpus: Optional[List[int]] = None
    rfs_enabled: Optional[bool] = None


@dataclass
class TimeSyncInfo:
    ntp_active: Optional[bool] = None
    chrony_active: Optional[bool] = None
    ptp_present: Optional[bool] = None
    clocksource: Optional[str] = None
    tsc_stable: Optional[bool] = None
    phc_devices: List[str] = field(default_factory=list)
    phc_interfaces: Dict[str, str] = field(
        default_factory=dict
    )  # iface -> phc


@dataclass
class PowerInfo:
    turbo_enabled: Optional[bool] = None
    speed_shift_enabled: Optional[bool] = None
    epp_value: Optional[str] = None
    cstate_limit: Optional[str] = None
    uncore_min_mhz: Optional[int] = None
    uncore_max_mhz: Optional[int] = None


@dataclass
class BootGuardrails:
    secure_boot: Optional[bool] = None
    iommu_enabled: Optional[bool] = None
    hpet_forced: Optional[bool] = None


@dataclass
class UserStackInfo:
    onload_version: Optional[str] = None
    vma_version: Optional[str] = None
    rdma_lib_version: Optional[str] = None


@dataclass
class ServicesInfo:
    irqbalance_active: Optional[bool] = None
    # Current tuned profile if active, None if inactive
    tuned_profile: Optional[str] = None


@dataclass
class HostInfo:
    hostname: str = field(default_factory=socket.gethostname)
    kernel: Optional[str] = None
    os: Optional[OSInfo] = None
    virtualization: Optional[str] = None
    collected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class Snapshot:
    host: HostInfo = field(default_factory=HostInfo)
    cpu: CpuInfo = field(default_factory=CpuInfo)
    numa: NumaInfo = field(default_factory=NumaInfo)
    memory: MemoryInfo = field(default_factory=MemoryInfo)
    nics: List[NicInfo] = field(default_factory=list)
    rdma: RdmaInfo = field(default_factory=RdmaInfo)
    irqs: List[IrqInfo] = field(default_factory=list)
    time_sync: TimeSyncInfo = field(default_factory=TimeSyncInfo)
    power: PowerInfo = field(default_factory=PowerInfo)
    boot: BootGuardrails = field(default_factory=BootGuardrails)
    user_stack: UserStackInfo = field(default_factory=UserStackInfo)
    services: ServicesInfo = field(default_factory=ServicesInfo)
    sysctl: SysctlInfo = field(default_factory=SysctlInfo)
    limits: LimitsInfo = field(default_factory=LimitsInfo)

    def to_dict(self) -> dict:
        """Serialize snapshot to a dict, dropping None values."""
        raw = asdict(self)
        if isinstance(raw["host"].get("collected_at"), datetime):
            raw["host"]["collected_at"] = raw["host"][
                "collected_at"
            ].isoformat()
        return _strip_none(raw)
