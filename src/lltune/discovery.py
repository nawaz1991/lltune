# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Discovery utilities to build a system snapshot."""

from __future__ import annotations

import logging
import platform
import re
from pathlib import Path
from typing import Dict, List, Optional

from .env import OSInfo, detect_virtualization, read_os_release
from .models import (
    BootGuardrails,
    CpuInfo,
    HostInfo,
    IrqInfo,
    LimitsInfo,
    MemoryInfo,
    NicInfo,
    NicQueues,
    NumaInfo,
    NumaNode,
    PowerInfo,
    RdmaInfo,
    ServicesInfo,
    Snapshot,
    SysctlInfo,
    TimeSyncInfo,
    UserStackInfo,
)
from .shell import run_cmd
from .utils import parse_cpulist as _utils_parse_cpulist

logger = logging.getLogger(__name__)


def parse_cmdline(path: Path = Path("/proc/cmdline")) -> Dict[str, str]:
    """Parse kernel cmdline into a dict of key->value (value may be empty string)."""
    if not path.exists():
        return {}
    tokens = path.read_text().strip().split()
    parsed: Dict[str, str] = {}
    for token in tokens:
        if "=" in token:
            key, _, value = token.partition("=")
            parsed[key] = value
        else:
            parsed[token] = ""
    return parsed


def _read_int(path: Path) -> Optional[int]:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _parse_lscpu() -> Dict[str, str]:
    info: Dict[str, str] = {}
    res = run_cmd(["lscpu"])
    if not res.ok:
        return info
    for line in res.stdout.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        info[key.strip()] = value.strip()
    return info


def _parse_cpulist(text: str) -> List[int]:
    """Parse a CPU list string, with graceful error handling for discovery."""
    try:
        return _utils_parse_cpulist(text)
    except ValueError as e:
        logger.warning("Invalid CPU list %r: %s", text, e)
        return []


def _safe_int(text: str, default: int = 0) -> int:
    """Safely parse an integer from text, handling empty strings and non-numeric values."""
    if not text:
        return default
    parts = text.split()
    if not parts or not parts[0]:
        return default
    try:
        return int(parts[0])
    except ValueError:
        return default


def collect_cpu_info(cmdline: Dict[str, str]) -> CpuInfo:
    info = CpuInfo()
    lscpu = _parse_lscpu()

    info.vendor = lscpu.get("Vendor ID")
    info.model_name = lscpu.get("Model name")
    info.family = lscpu.get("CPU family")
    info.model = lscpu.get("Model")
    info.sockets = _safe_int(lscpu.get("Socket(s)", "0"))
    info.cores_per_socket = _safe_int(lscpu.get("Core(s) per socket", "0"))
    info.threads_per_core = _safe_int(lscpu.get("Thread(s) per core", "0"))

    smt_active_path = Path("/sys/devices/system/cpu/smt/active")
    if smt_active_path.exists():
        smt_val = smt_active_path.read_text().strip()
        info.smt_enabled = smt_val == "1"
    elif info.threads_per_core:
        info.smt_enabled = info.threads_per_core > 1

    # Governors and freq
    cpu_root = Path("/sys/devices/system/cpu")
    for cpu_dir in cpu_root.glob("cpu[0-9]*"):
        try:
            cpu_id = int(cpu_dir.name.replace("cpu", ""))
        except ValueError:
            continue
        gov_path = cpu_dir / "cpufreq" / "scaling_governor"
        if gov_path.exists():
            info.per_cpu_governor[cpu_id] = gov_path.read_text().strip()

        freq_info: Dict[str, int] = {}
        min_path = cpu_dir / "cpufreq" / "scaling_min_freq"
        max_path = cpu_dir / "cpufreq" / "scaling_max_freq"
        min_freq = _read_int(min_path)
        max_freq = _read_int(max_path)
        if min_freq is not None:
            freq_info["min_khz"] = min_freq
        if max_freq is not None:
            freq_info["max_khz"] = max_freq
        if freq_info:
            info.per_cpu_freq[cpu_id] = freq_info

    info.cmdline_flags = cmdline
    return info


def collect_numa_info() -> NumaInfo:
    numa = NumaInfo()
    node_root = Path("/sys/devices/system/node")
    if not node_root.exists():
        return numa

    for node_dir in node_root.glob("node[0-9]*"):
        try:
            node_id = int(node_dir.name.replace("node", ""))
        except ValueError:
            continue
        cpulist_path = node_dir / "cpulist"
        meminfo_path = node_dir / "meminfo"

        cpus: List[int] = []
        if cpulist_path.exists():
            cpus = _parse_cpulist(cpulist_path.read_text().strip())

        mem_total_kb: Optional[int] = None
        mem_free_kb: Optional[int] = None
        if meminfo_path.exists():
            for line in meminfo_path.read_text().splitlines():
                if line.startswith("Node {} MemTotal".format(node_id)):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            mem_total_kb = int(parts[3])
                        except ValueError:
                            pass
                if line.startswith("Node {} MemFree".format(node_id)):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            mem_free_kb = int(parts[3])
                        except ValueError:
                            pass

        numa.nodes.append(
            NumaNode(
                node_id=node_id,
                cpus=cpus,
                mem_total_kb=mem_total_kb,
                mem_free_kb=mem_free_kb,
            )
        )
        for cpu_id in cpus:
            numa.cpu_to_node[cpu_id] = node_id

    return numa


def collect_power_info() -> PowerInfo:
    power = PowerInfo()
    turbo_path = Path("/sys/devices/system/cpu/intel_pstate/no_turbo")
    if turbo_path.exists():
        try:
            turbo_disabled = turbo_path.read_text().strip() == "1"
            power.turbo_enabled = not turbo_disabled
        except OSError:
            pass

    speedshift_path = Path("/sys/devices/system/cpu/intel_pstate/status")
    if speedshift_path.exists():
        status = speedshift_path.read_text().strip().lower()
        power.speed_shift_enabled = status in {"active", "on"}

    epp_path = Path(
        "/sys/devices/system/cpu/cpufreq/policy0/energy_performance_preference"
    )
    if epp_path.exists():
        try:
            power.epp_value = epp_path.read_text().strip()
        except OSError:
            pass

    cstate_path = Path("/sys/module/intel_idle/parameters/max_cstate")
    if cstate_path.exists():
        try:
            power.cstate_limit = cstate_path.read_text().strip()
        except OSError:
            pass

    uncore_min = Path("/sys/devices/system/cpu/intel_uncore_min_freq_khz")
    uncore_max = Path("/sys/devices/system/cpu/intel_uncore_max_freq_khz")
    power.uncore_min_mhz = _read_int(uncore_min)
    power.uncore_max_mhz = _read_int(uncore_max)
    if power.uncore_min_mhz:
        power.uncore_min_mhz //= 1000
    if power.uncore_max_mhz:
        power.uncore_max_mhz //= 1000
    return power


def collect_boot_guardrails() -> BootGuardrails:
    boot = BootGuardrails()

    secure_boot_var = Path(
        "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
    )
    if secure_boot_var.exists():
        try:
            data = secure_boot_var.read_bytes()
            boot.secure_boot = data[-1] == 1
        except OSError:
            pass

    iommu_cmdline = parse_cmdline()
    for key in ("intel_iommu", "amd_iommu", "iommu"):
        if key in iommu_cmdline:
            boot.iommu_enabled = iommu_cmdline[key] not in {"off", "0"}
            break

    hpet_force = Path(
        "/sys/devices/system/clocksource/clocksource0/available_clocksource"
    )
    if hpet_force.exists():
        current = Path(
            "/sys/devices/system/clocksource/clocksource0/current_clocksource"
        )
        try:
            current_val = current.read_text().strip()
            boot.hpet_forced = current_val.lower() == "hpet"
        except OSError:
            pass

    return boot


def collect_host_info(os_info: Optional[OSInfo]) -> HostInfo:
    host = HostInfo()
    host.os = os_info
    host.kernel = platform.release()
    host.virtualization = detect_virtualization()
    return host


def collect_memory_info() -> MemoryInfo:
    mem = MemoryInfo()
    meminfo = Path("/proc/meminfo")
    hp_size_kb: Optional[int] = None
    if meminfo.exists():
        lines = meminfo.read_text().splitlines()

        # First pass: capture hugepage size.
        for line in lines:
            if line.startswith("Hugepagesize:"):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        hp_size_kb = int(parts[1])
                    except ValueError:
                        hp_size_kb = None
                    size_key = f"{hp_size_kb}kB" if hp_size_kb else "unknown"
                    mem.hugepages.setdefault(size_key, {})["size_kb"] = parts[
                        1
                    ]

        size_key = f"{hp_size_kb}kB" if hp_size_kb else "unknown"

        # Second pass: capture totals and other fields.
        for line in lines:
            if line.startswith("MemTotal:"):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        mem.total_kb = int(parts[1])
                    except ValueError:
                        pass
            if line.startswith("HugePages_Total"):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        mem.hugepages.setdefault(size_key, {})["total"] = int(
                            parts[1]
                        )
                    except ValueError:
                        pass
            if line.startswith("HugePages_Free"):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        mem.hugepages.setdefault(size_key, {})["free"] = int(
                            parts[1]
                        )
                    except ValueError:
                        pass
    swap_path = Path("/proc/swaps")
    if swap_path.exists():
        for line in swap_path.read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 5:
                mem.swap_devices.append(
                    {
                        "device": parts[0],
                        "type": parts[1],
                        "size_kb": parts[2],
                        "used_kb": parts[3],
                    }
                )
    thp_base = Path("/sys/kernel/mm/transparent_hugepage")
    if thp_base.exists():
        enabled = thp_base / "enabled"
        defrag = thp_base / "defrag"
        if enabled.exists():
            mem.thp_enabled = enabled.read_text().strip()
        if defrag.exists():
            mem.thp_defrag = defrag.read_text().strip()
    numa_balance_path = Path("/proc/sys/kernel/numa_balancing")
    if numa_balance_path.exists():
        try:
            mem.numa_balancing = numa_balance_path.read_text().strip() == "1"
        except OSError:
            pass
    ksm_path = Path("/sys/kernel/mm/ksm/run")
    if ksm_path.exists():
        try:
            mem.ksm_enabled = ksm_path.read_text().strip() == "1"
        except OSError:
            pass

    # Per-node hugepages
    node_root = Path("/sys/devices/system/node")
    if node_root.exists():
        for node_dir in node_root.glob("node[0-9]*"):
            try:
                node_id = int(node_dir.name.replace("node", ""))
            except ValueError:
                continue
            hp_root = node_dir / "hugepages"
            if not hp_root.exists():
                continue
            for hp in hp_root.glob("hugepages-*"):
                size = hp.name.replace("hugepages-", "")
                nr_path = hp / "nr_hugepages"
                if nr_path.exists():
                    try:
                        nr = int(nr_path.read_text().strip())
                    except ValueError:
                        continue
                    node_key = f"node{node_id}"
                    mem.hugepages.setdefault(size, {}).setdefault(
                        "per_node", {}
                    )[node_key] = nr
    return mem


def collect_nic_info() -> List[NicInfo]:
    nics: List[NicInfo] = []
    ip_link = run_cmd(["ip", "-o", "link", "show"])
    if not ip_link.ok:
        return nics

    for line in ip_link.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        name = parts[1].strip()
        if name == "lo":
            continue
        nic = NicInfo(name=name)

        mac_match = re.search(r"link/(?:ether|loopback) ([0-9a-f:]{17})", line)
        if mac_match:
            nic.mac = mac_match.group(1)

        mtu_match = re.search(r"mtu (\d+)", line)
        if mtu_match:
            try:
                nic.mtu = int(mtu_match.group(1))
            except ValueError:
                pass

        ethtool_i = run_cmd(["ethtool", "-i", name])
        if ethtool_i.ok:
            for ln in ethtool_i.stdout.splitlines():
                if ln.startswith("driver:"):
                    nic.driver = ln.split(":", 1)[1].strip()
                elif ln.startswith("version:"):
                    nic.driver_version = ln.split(":", 1)[1].strip()
                elif ln.startswith("firmware-version:"):
                    nic.firmware_version = ln.split(":", 1)[1].strip()
                elif ln.startswith("bus-info:"):
                    nic.bus_info = ln.split(":", 1)[1].strip()

        ethtool_s = run_cmd(["ethtool", name])
        if ethtool_s.ok:
            for ln in ethtool_s.stdout.splitlines():
                if "Speed:" in ln:
                    speed_part = ln.split("Speed:", 1)[1].strip()
                    if speed_part.endswith("Mb/s"):
                        try:
                            nic.speed_mbps = int(
                                speed_part.replace("Mb/s", "").strip()
                            )
                        except ValueError:
                            pass
                if "Link detected:" in ln:
                    nic.link = ln.split("Link detected:", 1)[1].strip()

        ethtool_k = run_cmd(["ethtool", "-k", name])
        if ethtool_k.ok:
            for ln in ethtool_k.stdout.splitlines():
                if ":" not in ln:
                    continue
                key, _, value = ln.partition(":")
                nic.offloads[key.strip()] = value.strip()

        ethtool_c = run_cmd(["ethtool", "-c", name])
        if ethtool_c.ok:
            for ln in ethtool_c.stdout.splitlines():
                if ":" not in ln:
                    continue
                key, _, value = ln.partition(":")
                nic.coalescing[key.strip()] = value.strip()

        ethtool_g = run_cmd(["ethtool", "-g", name])
        if ethtool_g.ok:
            # ethtool -g output has two sections: "Pre-set maximums" and "Current hardware settings"
            # We capture both for recommendations (maximize ring buffers)
            in_max_section = False
            in_current_section = False
            for ln in ethtool_g.stdout.splitlines():
                if "Pre-set maximums" in ln:
                    in_max_section = True
                    in_current_section = False
                    continue
                if "Current hardware settings" in ln:
                    in_current_section = True
                    in_max_section = False
                    continue
                if ":" not in ln:
                    continue
                key, _, value = ln.partition(":")
                key = key.strip().lower()
                value = value.strip()
                if in_max_section:
                    if key == "rx":
                        try:
                            nic.rings["rx_max"] = int(value)
                        except ValueError:
                            pass
                    elif key == "tx":
                        try:
                            nic.rings["tx_max"] = int(value)
                        except ValueError:
                            pass
                elif in_current_section:
                    if key == "rx":
                        try:
                            nic.rings["rx"] = int(value)
                        except ValueError:
                            pass
                    elif key == "tx":
                        try:
                            nic.rings["tx"] = int(value)
                        except ValueError:
                            pass

        ethtool_a = run_cmd(["ethtool", "-a", name])
        if ethtool_a.ok:
            for ln in ethtool_a.stdout.splitlines():
                if ":" not in ln:
                    continue
                key, _, value = ln.partition(":")
                nic.flow_control[key.strip()] = value.strip()

        ethtool_l = run_cmd(["ethtool", "-l", name])
        if ethtool_l.ok:
            queues = NicQueues()
            for ln in ethtool_l.stdout.splitlines():
                parts_ln = ln.strip().split()
                if len(parts_ln) == 2 and parts_ln[0].lower() in {
                    "rx",
                    "tx",
                    "combined",
                }:
                    try:
                        val = int(parts_ln[1])
                    except ValueError:
                        continue
                    if parts_ln[0].lower() == "rx":
                        queues.rx_queues = val
                    elif parts_ln[0].lower() == "tx":
                        queues.tx_queues = val
                    elif parts_ln[0].lower() == "combined":
                        queues.combined = val
            nic.queues = queues

        numa_node_path = Path(f"/sys/class/net/{name}/device/numa_node")
        if numa_node_path.exists():
            try:
                val = int(numa_node_path.read_text().strip())
                nic.numa_node = val if val >= 0 else None
            except ValueError:
                pass

        # Vendor detection heuristic
        if nic.driver:
            drv = nic.driver.lower()
            if "sfc" in drv or "onload" in drv or "solarflare" in drv:
                nic.vendor = "solarflare"
            elif "mlx" in drv or "mellanox" in drv:
                nic.vendor = "mellanox"

        # RPS/XPS per queue (basic)
        rx_dir = Path(f"/sys/class/net/{name}/queues")
        if rx_dir.exists():
            for rxq in rx_dir.glob("rx-*"):
                rps = rxq / "rps_cpus"
                if rps.exists():
                    try:
                        nic.queues.rps[str(rxq.name)] = rps.read_text().strip()
                        # rps_flow_cnt is shared across queues under
                        # rx-<n>/rps_flow_cnt
                        rfc = rxq / "rps_flow_cnt"
                        if rfc.exists():
                            try:
                                nic.queues.rps_flow_cnt = int(
                                    rfc.read_text().strip() or "0"
                                )
                            except ValueError:
                                pass
                    except OSError:
                        pass
            for txq in rx_dir.glob("tx-*"):
                xps = txq / "xps_cpus"
                if xps.exists():
                    try:
                        nic.queues.xps[str(txq.name)] = xps.read_text().strip()
                    except OSError:
                        pass

        nics.append(nic)
    return nics


def collect_irq_info() -> List[IrqInfo]:
    irqs: List[IrqInfo] = []
    interrupts = Path("/proc/interrupts")
    if not interrupts.exists():
        return irqs
    lines = interrupts.read_text().splitlines()
    # First line is header with CPU columns
    header = lines[0] if lines else ""
    num_cpus = len([h for h in header.split() if h.startswith("CPU")])

    for line in lines[1:]:
        if not line or not line.strip()[0].isdigit():
            continue
        parts = line.split()
        irq_str = parts[0].strip(":")
        try:
            irq_num = int(irq_str)
        except ValueError:
            continue

        # Description is everything after IRQ number and CPU counts
        # Format: IRQ_NUM: CPU0_COUNT CPU1_COUNT ... CPUN_COUNT TYPE DESCRIPTION
        # The number of CPU count columns equals num_cpus
        desc_start_idx = 1 + num_cpus  # Skip IRQ number + CPU counts
        if len(parts) > desc_start_idx:
            desc = " ".join(parts[desc_start_idx:])
        else:
            desc = ""

        counts: Dict[int, int] = {}
        for idx in range(num_cpus):
            if 1 + idx < len(parts):
                try:
                    counts[idx] = int(parts[1 + idx])
                except ValueError:
                    continue
        irq = IrqInfo(irq=irq_num, description=desc, counts=counts)

        aff_path = Path(f"/proc/irq/{irq_num}/smp_affinity_list")
        if aff_path.exists():
            try:
                aff_list = aff_path.read_text().strip()
                irq.affinity = _parse_cpulist(aff_list)
            except OSError:
                pass

        # Try to extract NIC name from IRQ description (e.g., "eth0-TxRx-0" -> "eth0")
        # Common patterns: "eth0-TxRx-0", "enp1s0f0-0",
        # "mlx5_comp0@pci:0000:01:00.0"
        nic_name = None
        if desc:
            # Try common patterns
            for pattern_sep in ["-TxRx-", "-Tx-", "-Rx-", "-"]:
                if pattern_sep in desc:
                    nic_name = desc.split(pattern_sep)[0]
                    break
            # Check if this looks like a valid NIC
            if nic_name:
                nic_path = Path(f"/sys/class/net/{nic_name}")
                if not nic_path.exists():
                    nic_name = None

        if nic_name:
            rps_cpus_path = Path(
                f"/sys/class/net/{nic_name}/queues/rx-0/rps_cpus"
            )
            if rps_cpus_path.exists():
                try:
                    rps_val = rps_cpus_path.read_text().strip()
                    # rps_cpus is a hex mask, not a cpulist
                    irq.rps_cpus = _parse_hex_mask(rps_val)
                except OSError:
                    pass

        irqs.append(irq)
    return irqs


def _parse_hex_mask(mask: str) -> List[int]:
    """Parse a hex CPU mask (e.g., 'ff' or '00000000,0000000f') into a list of CPU IDs."""
    cpus: List[int] = []
    # Remove commas (used for >32 CPUs) and leading zeros
    mask = mask.replace(",", "").lstrip("0") or "0"
    try:
        val = int(mask, 16)
    except ValueError:
        return cpus
    bit = 0
    while val:
        if val & 1:
            cpus.append(bit)
        val >>= 1
        bit += 1
    return cpus


def irqbalance_active() -> Optional[bool]:
    status = run_cmd(["systemctl", "is-active", "irqbalance"])
    if status.returncode == 0:
        return True
    if status.returncode == 3:  # inactive/dead
        return False
    return None


def tuned_active() -> Optional[str]:
    """Return the current tuned profile if active, None otherwise."""
    status = run_cmd(["systemctl", "is-active", "tuned"])
    if status.returncode != 0:
        return None
    profile = run_cmd(["tuned-adm", "active"])
    if profile.ok:
        # Output is like "Current active profile: latency-performance"
        for line in profile.stdout.splitlines():
            if "Current active profile:" in line:
                return line.split(":", 1)[1].strip()
    return "active"


def collect_time_info() -> TimeSyncInfo:
    ts = TimeSyncInfo()
    timedatectl = run_cmd(["timedatectl", "status"])
    if timedatectl.ok:
        for ln in timedatectl.stdout.splitlines():
            if "NTP service" in ln:
                ts.ntp_active = "active" in ln.lower()
    chrony = run_cmd(["systemctl", "is-active", "chronyd"])
    if chrony.returncode == 0:
        ts.chrony_active = True
    ntpd = run_cmd(["systemctl", "is-active", "ntpd"])
    if ntpd.returncode == 0:
        ts.ntp_active = True
    ptp4l = run_cmd(["systemctl", "is-active", "ptp4l"])
    if ptp4l.returncode == 0:
        ts.ptp_present = True

    clocksource_cur = Path(
        "/sys/devices/system/clocksource/clocksource0/current_clocksource"
    )
    if clocksource_cur.exists():
        try:
            ts.clocksource = clocksource_cur.read_text().strip()
        except OSError:
            pass

    # Check TSC stability by looking at available clocksources and kernel messages
    # TSC is considered stable if it's listed in available_clocksource
    available_path = Path(
        "/sys/devices/system/clocksource/clocksource0/available_clocksource"
    )
    if available_path.exists():
        try:
            available = available_path.read_text().strip()
            ts.tsc_stable = "tsc" in available.split()
        except OSError:
            ts.tsc_stable = None
    else:
        ts.tsc_stable = None

    ptp_devices = Path("/sys/class/ptp")
    if ptp_devices.exists():
        for dev in ptp_devices.glob("ptp*"):
            ts.phc_devices.append(dev.name)
            for netdev in dev.glob("device/net/*"):
                ts.phc_interfaces[netdev.name] = dev.name
    return ts


def collect_rdma_info(nics: List[NicInfo]) -> RdmaInfo:
    """Collect RDMA devices and associate with NICs via sysfs."""
    rdma = RdmaInfo()
    rdma_class = Path("/sys/class/infiniband")
    if not rdma_class.exists():
        return rdma

    bus_by_nic = {nic.name: nic.bus_info for nic in nics if nic.bus_info}

    for dev in rdma_class.glob("*"):
        dev_name = dev.name
        rdma.devices.append({"name": dev_name})
        net_dir = dev / "device" / "net"
        if net_dir.exists():
            nets = [p.name for p in net_dir.iterdir() if p.is_dir()]
            if nets:
                rdma.associations[dev_name] = nets
                continue
        # fallback: use PCI bus to match
        try:
            # realpath of device might include PCI path
            pci_path = dev.resolve().parent
            pci_str = pci_path.name
        except Exception:
            pci_str = None
        if pci_str:
            matched = [
                nic
                for nic, bus in bus_by_nic.items()
                if bus and bus in pci_str
            ]
            if matched:
                rdma.associations[dev_name] = matched
    return rdma


def collect_user_stack_info() -> UserStackInfo:
    usr = UserStackInfo()
    onload = run_cmd(["onload", "--version"])
    if onload.ok:
        usr.onload_version = onload.stdout.strip()
    vma = run_cmd(["ldconfig", "-p"])
    if vma.ok:
        if "libvma" in vma.stdout:
            usr.vma_version = "present"
        if "libibverbs" in vma.stdout:
            usr.rdma_lib_version = "present"
    return usr


def collect_sysctl_info() -> SysctlInfo:
    """Collect current sysctl values for network and VM tuning."""
    sysctl = SysctlInfo()

    # Map of sysctl keys to SysctlInfo attributes and their types
    sysctl_map = {
        # Network buffer sizes
        "net/core/rmem_max": ("rmem_max", int),
        "net/core/wmem_max": ("wmem_max", int),
        "net/core/rmem_default": ("rmem_default", int),
        "net/core/wmem_default": ("wmem_default", int),
        "net/ipv4/tcp_rmem": ("tcp_rmem", str),
        "net/ipv4/tcp_wmem": ("tcp_wmem", str),
        "net/ipv4/udp_rmem_min": ("udp_rmem_min", int),
        "net/ipv4/udp_wmem_min": ("udp_wmem_min", int),
        # Low latency TCP settings
        "net/ipv4/tcp_timestamps": ("tcp_timestamps", int),
        "net/ipv4/tcp_sack": ("tcp_sack", int),
        "net/ipv4/tcp_low_latency": ("tcp_low_latency", int),
        "net/ipv4/tcp_fastopen": ("tcp_fastopen", int),
        "net/ipv4/tcp_tw_reuse": ("tcp_tw_reuse", int),
        "net/ipv4/tcp_fin_timeout": ("tcp_fin_timeout", int),
        # Busy polling
        "net/core/busy_poll": ("busy_poll", int),
        "net/core/busy_read": ("busy_read", int),
        # Backlog and queuing
        "net/core/netdev_max_backlog": ("netdev_max_backlog", int),
        "net/core/netdev_budget": ("netdev_budget", int),
        "net/core/somaxconn": ("somaxconn", int),
        # VM settings
        "vm/dirty_ratio": ("dirty_ratio", int),
        "vm/dirty_background_ratio": ("dirty_background_ratio", int),
        "vm/max_map_count": ("max_map_count", int),
        # File system
        "fs/file-max": ("file_max", int),
    }

    proc_sys = Path("/proc/sys")
    for sysctl_path, (attr_name, attr_type) in sysctl_map.items():
        path = proc_sys / sysctl_path
        if path.exists():
            try:
                value = path.read_text().strip()
                if attr_type == int:
                    # Handle multi-value sysctls like tcp_rmem that have "min default max"
                    # For int type, we take the first number if it's a simple
                    # value
                    parts = value.split()
                    if len(parts) == 1:
                        setattr(sysctl, attr_name, int(value))
                else:
                    setattr(sysctl, attr_name, value)
            except (OSError, ValueError):
                pass

    return sysctl


def collect_limits_info() -> LimitsInfo:
    """Collect current resource limits from /etc/security/limits.d/."""
    limits = LimitsInfo()

    # Check /etc/security/limits.conf and /etc/security/limits.d/*.conf
    limits_files = [Path("/etc/security/limits.conf")]
    limits_d = Path("/etc/security/limits.d")
    if limits_d.exists():
        limits_files.extend(sorted(limits_d.glob("*.conf")))

    # Track values (later files override earlier ones)
    memlock_soft = None
    memlock_hard = None
    nofile_soft = None
    nofile_hard = None
    nproc_soft = None
    nproc_hard = None

    for limits_file in limits_files:
        if not limits_file.exists():
            continue
        try:
            for line in limits_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 4:
                    continue
                # Format: domain type item value
                # domain can be *, @group, or username
                # type is soft or hard
                # item is memlock, nofile, nproc, etc.
                domain, limit_type, item, value = (
                    parts[0],
                    parts[1],
                    parts[2],
                    parts[3],
                )

                # We look for * (all users) or root entries
                if domain not in ("*", "root"):
                    continue

                if item == "memlock":
                    if limit_type in ("soft", "-"):
                        memlock_soft = value
                    if limit_type in ("hard", "-"):
                        memlock_hard = value
                elif item == "nofile":
                    try:
                        val = int(value)
                        if limit_type in ("soft", "-"):
                            nofile_soft = val
                        if limit_type in ("hard", "-"):
                            nofile_hard = val
                    except ValueError:
                        pass
                elif item == "nproc":
                    try:
                        val = int(value)
                        if limit_type in ("soft", "-"):
                            nproc_soft = val
                        if limit_type in ("hard", "-"):
                            nproc_hard = val
                    except ValueError:
                        pass
        except OSError:
            pass

    limits.memlock_soft = memlock_soft
    limits.memlock_hard = memlock_hard
    limits.nofile_soft = nofile_soft
    limits.nofile_hard = nofile_hard
    limits.nproc_soft = nproc_soft
    limits.nproc_hard = nproc_hard

    return limits


def collect_snapshot() -> Snapshot:
    """Collect a best-effort snapshot with low-risk probes."""
    os_info = read_os_release()
    cmdline = parse_cmdline()
    snapshot = Snapshot()
    snapshot.host = collect_host_info(os_info)
    snapshot.cpu = collect_cpu_info(cmdline)
    snapshot.numa = collect_numa_info()
    snapshot.power = collect_power_info()
    snapshot.boot = collect_boot_guardrails()
    snapshot.memory = collect_memory_info()
    snapshot.nics = collect_nic_info()
    snapshot.irqs = collect_irq_info()
    snapshot.rdma = collect_rdma_info(snapshot.nics)
    snapshot.time_sync = collect_time_info()
    snapshot.user_stack = collect_user_stack_info()
    snapshot.services = ServicesInfo(
        irqbalance_active=irqbalance_active(), tuned_profile=tuned_active()
    )
    snapshot.sysctl = collect_sysctl_info()
    snapshot.limits = collect_limits_info()
    return snapshot
