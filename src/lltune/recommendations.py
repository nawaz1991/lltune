# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Recommendation engine for low-latency tuning."""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

from .models import Snapshot
from .utils import parse_cpulist as _utils_parse_cpulist

logger = logging.getLogger(__name__)


@dataclass
class Recommendation:
    category: str
    item: str
    current: Optional[str]
    target: Optional[str]
    impact: str  # low/medium/high
    rationale: str
    severity: str = "info"  # info/warning/error
    risk: Optional[str] = None  # safe/potentially_disruptive/high_risk

    def to_dict(self) -> Dict[str, Optional[str]]:
        return asdict(self)


def _all_governors(snapshot: Snapshot) -> List[str]:
    return list(set(snapshot.cpu.per_cpu_governor.values()))


def _parse_cpulist(text: str) -> List[int]:
    """Parse a CPU list string like '0-3,8-11' into a list of integers.

    Wrapper around utils.parse_cpulist that handles TODO placeholders.
    """
    if not text or "TODO" in text:
        return []
    try:
        return _utils_parse_cpulist(text)
    except ValueError as e:
        logger.warning("Invalid CPU list %r: %s", text, e)
        return []


def _mask_to_cpus(mask: str) -> List[int]:
    """Convert hex CPU mask (e.g. 'ff') to list of CPU IDs."""
    cpus: List[int] = []
    if not mask:
        return cpus
    # Handle comma-separated 32-bit chunks (e.g., 'ff,00000000' for >32 CPUs)
    mask = mask.replace(",", "").strip()
    try:
        val = int(mask, 16)
    except ValueError:
        return cpus
    bit = 0
    while val > 0:
        if val & 1:
            cpus.append(bit)
        val >>= 1
        bit += 1
    return cpus


def build_recommendations(snapshot: Snapshot) -> List[Recommendation]:
    recs: List[Recommendation] = []
    snap = snapshot

    # CPU governor
    governors = _all_governors(snap)
    if governors and any(gov.lower() != "performance" for gov in governors):
        recs.append(
            Recommendation(
                category="cpu",
                item="governor",
                current=",".join(governors),
                target="performance",
                impact="high",
                rationale=(
                    "Ensure consistent low latency by locking "
                    "CPUs to performance governor."
                ),
                severity="warning",
            )
        )

    # SMT
    if snap.cpu.smt_enabled:
        recs.append(
            Recommendation(
                category="cpu",
                item="smt",
                current="enabled",
                target="disable or isolate critical cores",
                impact="medium",
                rationale=(
                    "Hyper-Threading can increase jitter; "
                    "disable or avoid sharing critical cores."
                ),
                severity="info",
                risk="potentially_disruptive",
            )
        )

    # isolcpus/nohz_full/rcu_nocbs
    cmdline = snap.cpu.cmdline_flags or {}
    if "isolcpus" not in cmdline or "nohz_full" not in cmdline:
        recs.append(
            Recommendation(
                category="kernel",
                item="isolcpus/nohz_full",
                current="missing",
                target="set for trading cores",
                impact="high",
                rationale=(
                    "Isolate trading cores from scheduler/RCU "
                    "noise using isolcpus/nohz_full."
                ),
                severity="warning",
                risk="potentially_disruptive",
            )
        )

    # skew_tick - reduces jitter from timer alignment
    if "skew_tick" not in cmdline and "isolcpus" in cmdline:
        recs.append(
            Recommendation(
                category="kernel",
                item="skew_tick",
                current="not set",
                target="skew_tick=1",
                impact="medium",
                rationale=(
                    "Add skew_tick=1 to reduce jitter from "
                    "timer tick alignment across CPUs."
                ),
                severity="info",
            )
        )

    # tsc=reliable - mark TSC as reliable
    if "tsc" not in cmdline:
        recs.append(
            Recommendation(
                category="kernel",
                item="tsc",
                current="not set",
                target="tsc=reliable",
                impact="low",
                rationale=(
                    "Mark TSC as reliable for accurate "
                    "timekeeping (tsc=reliable)."
                ),
                severity="info",
            )
        )

    # nosoftlockup - disable soft lockup detector
    if "nosoftlockup" not in cmdline and "isolcpus" in cmdline:
        recs.append(
            Recommendation(
                category="kernel",
                item="nosoftlockup",
                current="not set",
                target="nosoftlockup",
                impact="medium",
                rationale=(
                    "Add nosoftlockup to prevent soft lockup "
                    "warnings on isolated spinning cores."
                ),
                severity="info",
            )
        )

    # nmi_watchdog - disable for isolated cores
    if cmdline.get("nmi_watchdog") not in ("0", 0) and "isolcpus" in cmdline:
        recs.append(
            Recommendation(
                category="kernel",
                item="nmi_watchdog",
                current=str(cmdline.get("nmi_watchdog", "enabled")),
                target="nmi_watchdog=0",
                impact="medium",
                rationale=(
                    "Disable NMI watchdog to reduce interrupt "
                    "noise on isolated cores."
                ),
                severity="info",
            )
        )

    # intel_pstate - disable for better governor control
    if "intel_pstate" not in cmdline:
        recs.append(
            Recommendation(
                category="kernel",
                item="intel_pstate",
                current="default (enabled)",
                target="intel_pstate=disable",
                impact="medium",
                rationale=(
                    "Disable intel_pstate driver to use "
                    "acpi-cpufreq for better P-state control."
                ),
                severity="info",
                risk="potentially_disruptive",
            )
        )

    # rcu_nocbs - critical for full isolation
    if "isolcpus" in cmdline and "rcu_nocbs" not in cmdline:
        recs.append(
            Recommendation(
                category="kernel",
                item="rcu_nocbs",
                current="missing",
                target="match isolcpus",
                impact="high",
                rationale=(
                    "Add rcu_nocbs to offload RCU callbacks from "
                    "isolated cores; without it, RCU callbacks "
                    "still run on those cores."
                ),
                severity="warning",
                risk="potentially_disruptive",
            )
        )
    elif "isolcpus" in cmdline and "rcu_nocbs" in cmdline:
        # Validate they match
        iso_cpus = _parse_cpulist(str(cmdline.get("isolcpus", "")))
        rcu_cpus = _parse_cpulist(str(cmdline.get("rcu_nocbs", "")))
        if set(iso_cpus) != set(rcu_cpus) and iso_cpus and rcu_cpus:
            missing = set(iso_cpus) - set(rcu_cpus)
            if missing:
                recs.append(
                    Recommendation(
                        category="kernel",
                        item="rcu_nocbs",
                        current=f"CPUs {
                            sorted(rcu_cpus)}",
                        target=f"include CPUs {
                            sorted(missing)}",
                        impact="medium",
                        rationale=(
                            "rcu_nocbs should cover all isolated "
                            "CPUs to fully offload RCU callbacks."
                        ),
                        severity="info",
                    )
                )

    # idle=poll warning - high CPU usage
    if cmdline.get("idle") == "poll":
        recs.append(
            Recommendation(
                category="kernel",
                item="idle=poll",
                current="enabled",
                target="consider removing if power/heat is concern",
                impact="medium",
                rationale=(
                    "idle=poll keeps CPUs spinning which minimizes "
                    "wakeup latency but uses 100% CPU and generates "
                    "heat. Only use if latency is paramount."
                ),
                severity="info",
                risk="potentially_disruptive",
            )
        )
    elif "isolcpus" in cmdline and cmdline.get("idle") != "poll":
        recs.append(
            Recommendation(
                category="kernel",
                item="idle=poll",
                current="not set",
                target="idle=poll for ultra-low latency",
                impact="high",
                rationale=(
                    "Consider idle=poll to eliminate C-state wakeup "
                    "latency on isolated cores. Warning: causes "
                    "100% CPU usage."
                ),
                severity="info",
                risk="high_risk",
            )
        )
    # Turbo / power
    if snap.power and snap.power.turbo_enabled is True:
        recs.append(
            Recommendation(
                category="cpu",
                item="turbo",
                current="enabled",
                target="disable for determinism",
                impact="medium",
                rationale=(
                    "CPU turbo can add jitter; disable for "
                    "consistent latency."
                ),
                severity="info",
                risk="potentially_disruptive",
            )
        )

    # THP
    thp = (snap.memory.thp_enabled or "").lower()
    if thp and "never" not in thp:
        recs.append(
            Recommendation(
                category="memory",
                item="thp_runtime",
                current=thp,
                target="never",
                impact="high",
                rationale=(
                    "Disable THP to reduce latency spikes "
                    "from page faults/compaction."
                ),
                severity="warning",
                risk="potentially_disruptive",
            )
        )

    # Swap
    if snap.memory.swap_devices:
        recs.append(
            Recommendation(
                category="memory",
                item="swap",
                current=f"{len(snap.memory.swap_devices)} devices",
                target="disable",
                impact="high",
                rationale=(
                    "Disable swap to avoid paging delays "
                    "on latency-sensitive workloads."
                ),
                severity="warning",
                risk="potentially_disruptive",
            )
        )

    # NUMA balancing
    if snap.memory.numa_balancing:
        recs.append(
            Recommendation(
                category="memory",
                item="numa_balancing",
                current="enabled",
                target="disable",
                impact="medium",
                rationale=(
                    "NUMA auto-balancing can migrate pages and "
                    "add jitter; disable for pinned workloads."
                ),
                severity="info",
            )
        )

    # KSM
    if snap.memory.ksm_enabled:
        recs.append(
            Recommendation(
                category="memory",
                item="ksm",
                current="enabled",
                target="disable",
                impact="medium",
                rationale=(
                    "KSM scanning can add latency; typically "
                    "disabled on HFT nodes."
                ),
                severity="info",
            )
        )

    # irqbalance
    if snap.services.irqbalance_active:
        recs.append(
            Recommendation(
                category="services",
                item="irqbalance",
                current="enabled",
                target="disable",
                impact="high",
                rationale=(
                    "irqbalance can move IRQs unpredictably; "
                    "pin IRQs manually for determinism."
                ),
                severity="warning",
            )
        )

    # NIC offloads
    offload_keys = [
        "generic-receive-offload",
        "large-receive-offload",
        "tcp-segmentation-offload",
        "generic-segmentation-offload",
    ]
    for nic in snap.nics:
        nic_offs = nic.offloads or {}
        bad = [
            k for k in offload_keys if k in nic_offs and "on" in nic_offs[k]
        ]
        if bad:
            recs.append(
                Recommendation(
                    category="nic",
                    item=f"{
                        nic.name}:offloads",
                    current=", ".join(bad),
                    target="disable",
                    impact="high",
                    rationale=(
                        "Disable GRO/LRO/TSO/GSO on latency-critical "
                        "NICs to avoid batching delays."
                    ),
                    severity="warning",
                )
            )
        # Coalescing >0
        coal = nic.coalescing or {}
        noisy = [
            k
            for k, v in coal.items()
            if v not in {"0", "0.000"} and k.startswith(("rx-", "tx-"))
        ]
        if noisy:
            recs.append(
                Recommendation(
                    category="nic",
                    item=f"{
                        nic.name}:coalescing",
                    current="; ".join(
                        f"{k}={
                            coal[k]}"
                        for k in noisy
                    ),
                    target="0",
                    impact="high",
                    rationale=(
                        "Set NIC coalescing timers to 0 to minimize "
                        "latency on trading paths."
                    ),
                    severity="warning",
                )
            )
        # RPS/XPS
        if (
            nic.queues
            and nic.queues.rps_flow_cnt
            and nic.queues.rps_flow_cnt > 0
        ):
            recs.append(
                Recommendation(
                    category="nic",
                    item=f"{
                        nic.name}:rps",
                    current=f"rps_flow_cnt={
                        nic.queues.rps_flow_cnt}",
                    target="disable for latency-critical queues",
                    impact="medium",
                    rationale=(
                        "RPS can add cross-CPU wakeups; disable "
                        "on latency-critical queues."
                    ),
                    severity="info",
                )
            )

        # Ring buffer sizes - check if not maximized
        if nic.rings:
            current_rx = nic.rings.get("rx")
            max_rx = nic.rings.get("rx_max")
            current_tx = nic.rings.get("tx")
            max_tx = nic.rings.get("tx_max")
            if current_rx and max_rx and current_rx < max_rx:
                recs.append(
                    Recommendation(
                        category="nic",
                        item=f"{
                            nic.name}:ring_rx",
                        current=str(current_rx),
                        target=str(max_rx),
                        impact="medium",
                        rationale=(
                            "Maximize RX ring buffer to reduce "
                            "packet drops under burst."
                        ),
                        severity="info",
                    )
                )
            if current_tx and max_tx and current_tx < max_tx:
                recs.append(
                    Recommendation(
                        category="nic",
                        item=f"{
                            nic.name}:ring_tx",
                        current=str(current_tx),
                        target=str(max_tx),
                        impact="medium",
                        rationale=(
                            "Maximize TX ring buffer to reduce "
                            "drops under burst."
                        ),
                        severity="info",
                    )
                )

    # Cross-NUMA IRQ affinity detection
    nic_numa_map = {
        nic.name: nic.numa_node
        for nic in snap.nics
        if nic.numa_node is not None
    }
    for irq in snap.irqs:
        if not irq.description or not irq.affinity:
            continue
        # Try to match IRQ to a NIC
        for nic_name, nic_numa in nic_numa_map.items():
            if nic_name in irq.description:
                # Check if IRQ affinity includes CPUs from different NUMA
                # irq.affinity is already List[int], no conversion needed
                irq_cpus = irq.affinity
                if irq_cpus and snap.numa and snap.numa.nodes:
                    cross_numa = False
                    for node in snap.numa.nodes:
                        node_cpus = set(node.cpus) if node.cpus else set()
                        irq_cpu_set = set(irq_cpus)
                        # If IRQ is bound to CPUs not on the NIC's NUMA node
                        if node.node_id == nic_numa:
                            if (
                                not irq_cpu_set.issubset(node_cpus)
                                and irq_cpu_set
                            ):
                                cross_numa = True
                                break
                    if cross_numa:
                        recs.append(
                            Recommendation(
                                category="irq",
                                item=f"{
                                    irq.irq}:{
                                    irq.description}",
                                current=f"cross-NUMA (NIC on node {nic_numa})",
                                target=f"pin to NUMA node {nic_numa} CPUs",
                                impact="high",
                                rationale=(
                                    "IRQ affinity crosses NUMA boundary; "
                                    "pin to NIC-local CPUs."
                                ),
                                severity="warning",
                            )
                        )
                break

    # tuned profile recommendation
    if snap.services.tuned_profile:
        profile = snap.services.tuned_profile
        if (
            "latency" not in profile.lower()
            and "performance" not in profile.lower()
        ):
            recs.append(
                Recommendation(
                    category="services",
                    item="tuned_profile",
                    current=profile,
                    target="latency-performance or network-latency",
                    impact="medium",
                    rationale=(
                        "Use a latency-optimized tuned profile "
                        "for low-latency workloads."
                    ),
                    severity="info",
                )
            )
    elif not snap.services.tuned_profile:
        # tuned not active - recommend it as a baseline
        recs.append(
            Recommendation(
                category="services",
                item="tuned",
                current="not active",
                target="enable with latency-performance profile",
                impact="medium",
                rationale=(
                    "Consider using tuned with latency-performance "
                    "profile as a baseline tuning layer."
                ),
                severity="info",
            )
        )

    # Clocksource/Chrony/PTP
    ts = snap.time_sync
    if ts.clocksource and ts.clocksource.lower() != "tsc":
        recs.append(
            Recommendation(
                category="time",
                item="clocksource",
                current=ts.clocksource,
                target="tsc",
                impact="medium",
                rationale="Use TSC for lowest-latency timekeeping if stable.",
                severity="info",
            )
        )
    if ts.ntp_active is False and ts.chrony_active is not True:
        recs.append(
            Recommendation(
                category="time",
                item="time_sync",
                current="inactive",
                target="chrony/ntp active",
                impact="medium",
                rationale=(
                    "Ensure time sync (chrony/NTP) is active for "
                    "correct sequencing and PTP fallback."
                ),
                severity="warning",
            )
        )
    if ts.ptp_present is not True and snap.boot.secure_boot is False:
        recs.append(
            Recommendation(
                category="time",
                item="ptp",
                current="absent",
                target="deploy ptp4l/phc2sys on PHC NICs",
                impact="medium",
                rationale=(
                    "PTP reduces drift for sub-microsecond "
                    "accuracy; configure if supported."
                ),
                severity="info",
            )
        )

    # Mitigations
    mitig = cmdline.get("mitigations")
    if mitig and mitig != "off":
        recs.append(
            Recommendation(
                category="kernel",
                item="mitigations",
                current=mitig,
                target="off (if risk accepted)",
                impact="medium",
                rationale=(
                    "Kernel mitigations add overhead; consider "
                    "mitigations=off if security posture allows."
                ),
                severity="info",
                risk="high_risk",
            )
        )

    # transparent hugepage cmdline
    if "transparent_hugepage" not in cmdline:
        recs.append(
            Recommendation(
                category="kernel",
                item="transparent_hugepage",
                current="missing",
                target="transparent_hugepage=never",
                impact="medium",
                rationale=(
                    "Add transparent_hugepage=never to ensure "
                    "THP stays disabled after reboot."
                ),
                severity="warning",
                risk="potentially_disruptive",
            )
        )

    # Network sysctl recommendations
    sysctl = snap.sysctl
    if sysctl:
        # Busy polling - critical for HFT
        if sysctl.busy_poll is not None and sysctl.busy_poll == 0:
            recs.append(
                Recommendation(
                    category="sysctl",
                    item="busy_poll",
                    current="0",
                    target="50-100",
                    impact="high",
                    rationale=(
                        "Enable busy polling (net.core.busy_poll=50) "
                        "to reduce latency on socket operations "
                        "by spinning instead of sleeping."
                    ),
                    severity="warning",
                )
            )
        if sysctl.busy_read is not None and sysctl.busy_read == 0:
            recs.append(
                Recommendation(
                    category="sysctl",
                    item="busy_read",
                    current="0",
                    target="50-100",
                    impact="high",
                    rationale=(
                        "Enable busy read (net.core.busy_read=50) "
                        "to reduce latency on socket reads."
                    ),
                    severity="warning",
                )
            )

        # TCP timestamps - disable for HFT
        if sysctl.tcp_timestamps is not None and sysctl.tcp_timestamps == 1:
            recs.append(
                Recommendation(
                    category="sysctl",
                    item="tcp_timestamps",
                    current="1",
                    target="0",
                    impact="medium",
                    rationale=(
                        "Disable TCP timestamps (tcp_timestamps=0) "
                        "to reduce packet overhead on "
                        "latency-critical connections."
                    ),
                    severity="info",
                    risk="potentially_disruptive",
                )
            )

        # TCP SACK - disable for HFT
        if sysctl.tcp_sack is not None and sysctl.tcp_sack == 1:
            recs.append(
                Recommendation(
                    category="sysctl",
                    item="tcp_sack",
                    current="1",
                    target="0",
                    impact="medium",
                    rationale=(
                        "Disable TCP SACK (tcp_sack=0) for more "
                        "predictable latency; only disable if "
                        "packet loss is rare."
                    ),
                    severity="info",
                    risk="potentially_disruptive",
                )
            )

        # Buffer sizes - check if using small defaults
        if sysctl.rmem_max is not None and sysctl.rmem_max < 16777216:  # 16MB
            recs.append(
                Recommendation(
                    category="sysctl",
                    item="rmem_max",
                    current=str(sysctl.rmem_max),
                    target="67108864 (64MB)",
                    impact="medium",
                    rationale=(
                        "Increase net.core.rmem_max to handle "
                        "burst traffic without drops."
                    ),
                    severity="info",
                )
            )
        if sysctl.wmem_max is not None and sysctl.wmem_max < 16777216:  # 16MB
            recs.append(
                Recommendation(
                    category="sysctl",
                    item="wmem_max",
                    current=str(sysctl.wmem_max),
                    target="67108864 (64MB)",
                    impact="medium",
                    rationale=(
                        "Increase net.core.wmem_max to handle "
                        "burst traffic without drops."
                    ),
                    severity="info",
                )
            )

        # Backlog - check if using small default
        if (
            sysctl.netdev_max_backlog is not None
            and sysctl.netdev_max_backlog < 10000
        ):
            recs.append(
                Recommendation(
                    category="sysctl",
                    item="netdev_max_backlog",
                    current=str(sysctl.netdev_max_backlog),
                    target="250000",
                    impact="medium",
                    rationale=(
                        "Increase netdev_max_backlog to prevent "
                        "packet drops under burst loads."
                    ),
                    severity="info",
                )
            )

        # Somaxconn - check if using small default
        if sysctl.somaxconn is not None and sysctl.somaxconn < 4096:
            recs.append(
                Recommendation(
                    category="sysctl",
                    item="somaxconn",
                    current=str(sysctl.somaxconn),
                    target="65535",
                    impact="low",
                    rationale=(
                        "Increase somaxconn to handle high "
                        "connection rates."
                    ),
                    severity="info",
                )
            )

        # File descriptor limits
        if sysctl.file_max is not None and sysctl.file_max < 1000000:
            recs.append(
                Recommendation(
                    category="sysctl",
                    item="file_max",
                    current=str(sysctl.file_max),
                    target="2097152",
                    impact="low",
                    rationale=(
                        "Increase fs.file-max to support "
                        "high-connection workloads."
                    ),
                    severity="info",
                )
            )

        # vm.max_map_count - important for memory-intensive apps
        if sysctl.max_map_count is not None and sysctl.max_map_count < 262144:
            recs.append(
                Recommendation(
                    category="sysctl",
                    item="max_map_count",
                    current=str(sysctl.max_map_count),
                    target="262144+",
                    impact="medium",
                    rationale=(
                        "Increase vm.max_map_count to support "
                        "memory-mapped apps and hugepages."
                    ),
                    severity="info",
                )
            )

    # Memory locking limits
    limits = snap.limits
    if limits:
        if limits.memlock_soft is None or (
            limits.memlock_soft != "unlimited" and limits.memlock_soft != "-1"
        ):
            recs.append(
                Recommendation(
                    category="limits",
                    item="memlock",
                    current=(
                        str(limits.memlock_soft)
                        if limits.memlock_soft
                        else "default"
                    ),
                    target="unlimited",
                    impact="high",
                    rationale=(
                        "Set memlock to unlimited to allow apps "
                        "to lock memory and avoid page faults."
                    ),
                    severity="warning",
                )
            )
        if limits.nofile_soft is not None and limits.nofile_soft < 65536:
            recs.append(
                Recommendation(
                    category="limits",
                    item="nofile",
                    current=str(limits.nofile_soft),
                    target="1048576",
                    impact="medium",
                    rationale=(
                        "Increase nofile limit to support "
                        "high-connection workloads."
                    ),
                    severity="info",
                )
            )

    # Onload/VMA/RDMA hints
    if snap.user_stack.onload_version and any(
        n.vendor == "solarflare" for n in snap.nics
    ):
        recs.append(
            Recommendation(
                category="onload",
                item="driver_alignment",
                current=snap.user_stack.onload_version,
                target="verify onload opts match Solarflare NIC profile",
                impact="medium",
                rationale=(
                    "Align Onload stack options with Solarflare "
                    "NIC tuning for consistent latency."
                ),
                severity="info",
            )
        )
    if snap.user_stack.vma_version and any(
        n.vendor == "mellanox" for n in snap.nics
    ):
        recs.append(
            Recommendation(
                category="vma",
                item="driver_alignment",
                current=snap.user_stack.vma_version,
                target="verify VMA opts match Mellanox profile",
                impact="medium",
                rationale="Align VMA stack options with Mellanox NIC tuning.",
                severity="info",
            )
        )
    if snap.rdma.devices and snap.nics:
        nic_nodes = {n.name: n.numa_node for n in snap.nics}
        for dev in snap.rdma.devices:
            name = dev.get("name") or dev.get("device") or "rdma"
            netdevs = snap.rdma.associations.get(name, [])
            nodes = {
                nic_nodes.get(nd)
                for nd in netdevs
                if nic_nodes.get(nd) is not None
            }
            if len(nodes) > 1:
                recs.append(
                    Recommendation(
                        category="rdma",
                        item=name,
                        current="cross-numa",
                        target="align RDMA devices to NIC NUMA nodes",
                        impact="medium",
                        rationale=(
                            "Keep RDMA/PHC paths NUMA-local "
                            "to reduce latency."
                        ),
                        severity="info",
                    )
                )

    return recs
