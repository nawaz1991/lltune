# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Pre/post validation hooks for latency measurement and verification.

This module provides hooks that can be run before and after applying tuning
to measure the impact and verify correctness of changes.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .utils import parse_cpulist as _utils_parse_cpulist

logger = logging.getLogger(__name__)


@dataclass
class LatencyStats:
    """Latency statistics from cyclictest or similar tool."""

    min_us: Optional[float] = None
    avg_us: Optional[float] = None
    max_us: Optional[float] = None
    p99_us: Optional[float] = None
    samples: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class IrqRates:
    """IRQ interrupt rates per second."""

    irq_rates: Dict[str, float] = field(default_factory=dict)
    duration_secs: float = 0.0
    total_interrupts: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PtpStatus:
    """PTP synchronization status."""

    offset_ns: Optional[float] = None
    jitter_ns: Optional[float] = None
    clock_state: Optional[str] = None
    interface: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class NicStats:
    """NIC statistics delta over measurement period."""

    interface: str = ""
    rx_packets: int = 0
    tx_packets: int = 0
    rx_errors: int = 0
    tx_errors: int = 0
    rx_dropped: int = 0
    tx_dropped: int = 0
    duration_secs: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ValidationResult:
    """Combined validation result from all hooks."""

    timestamp: str = ""
    phase: str = ""  # "pre" or "post"
    latency: Optional[LatencyStats] = None
    irq_rates: Optional[IrqRates] = None
    ptp_status: Optional[PtpStatus] = None
    nic_stats: List[NicStats] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        result = {
            "timestamp": self.timestamp,
            "phase": self.phase,
            "errors": self.errors,
        }
        if self.latency:
            result["latency"] = self.latency.to_dict()
        if self.irq_rates:
            result["irq_rates"] = self.irq_rates.to_dict()
        if self.ptp_status:
            result["ptp_status"] = self.ptp_status.to_dict()
        if self.nic_stats:
            result["nic_stats"] = [s.to_dict() for s in self.nic_stats]
        return result


def run_cyclictest(
    duration_secs: int = 10,
    cpus: Optional[List[int]] = None,
    priority: int = 99,
) -> Optional[LatencyStats]:
    """Run cyclictest to measure scheduling latency.

    Args:
        duration_secs: How long to run the test
        cpus: List of CPUs to test (None = all)
        priority: RT priority for test threads

    Returns:
        LatencyStats with measured values, or None if cyclictest unavailable
    """
    cyclictest = shutil.which("cyclictest")
    if not cyclictest:
        logger.warning("cyclictest not found; skipping latency measurement")
        return None

    cmd = [
        cyclictest,
        "-q",  # Quiet (no per-thread output)
        "-m",  # Lock memory
        "-n",  # Use nanosleep
        f"-D{duration_secs}",  # Duration
        f"-p{priority}",  # Priority
        "--json",  # JSON output if supported
    ]

    if cpus:
        cpu_list = ",".join(str(c) for c in cpus)
        cmd.extend(["-a", cpu_list, f"-t{len(cpus)}"])
    else:
        cmd.append("-t")  # One thread per CPU

    logger.info("Running cyclictest for %d seconds", duration_secs)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=duration_secs + 30,
        )

        if result.returncode != 0:
            logger.warning("cyclictest failed: %s", result.stderr)
            return None

        # Try to parse JSON output first
        try:
            data = json.loads(result.stdout)
            # cyclictest JSON format varies; try common structures
            if "thread" in data:
                threads = data.get("thread", {})
                mins = [
                    t.get("min", 0)
                    for t in threads.values()
                    if isinstance(t, dict)
                ]
                maxs = [
                    t.get("max", 0)
                    for t in threads.values()
                    if isinstance(t, dict)
                ]
                avgs = [
                    t.get("avg", 0)
                    for t in threads.values()
                    if isinstance(t, dict)
                ]
                return LatencyStats(
                    min_us=min(mins) / 1000 if mins else None,
                    max_us=max(maxs) / 1000 if maxs else None,
                    avg_us=sum(avgs) / len(avgs) / 1000 if avgs else None,
                )
        except json.JSONDecodeError:
            pass

        # Parse text output as fallback
        # Look for lines like "# Min Latencies: 00001 00001 ..."
        lines = result.stdout.strip().split("\n")
        stats = LatencyStats()
        for line in lines:
            if line.startswith("# Min Latencies:"):
                vals = [
                    int(x) for x in line.split(":")[1].split() if x.isdigit()
                ]
                stats.min_us = min(vals) if vals else None
            elif line.startswith("# Max Latencies:"):
                vals = [
                    int(x) for x in line.split(":")[1].split() if x.isdigit()
                ]
                stats.max_us = max(vals) if vals else None
            elif line.startswith("# Avg Latencies:"):
                vals = [
                    int(x) for x in line.split(":")[1].split() if x.isdigit()
                ]
                stats.avg_us = sum(vals) / len(vals) if vals else None

        return stats if stats.min_us is not None else None

    except subprocess.TimeoutExpired:
        logger.error("cyclictest timed out")
        return None
    except OSError as exc:
        logger.error("Failed to run cyclictest: %s", exc)
        return None


def sample_irq_rates(duration_secs: int = 5) -> Optional[IrqRates]:
    """Sample IRQ rates by reading /proc/interrupts twice.

    Args:
        duration_secs: Time between samples

    Returns:
        IrqRates with per-IRQ rates, or None on failure
    """
    interrupts = Path("/proc/interrupts")
    if not interrupts.exists():
        return None

    def parse_interrupts() -> Dict[str, int]:
        """Parse /proc/interrupts and return total per IRQ."""
        result = {}
        lines = interrupts.read_text().splitlines()
        for line in lines[1:]:  # Skip header
            parts = line.split()
            if not parts:
                continue
            irq_id = parts[0].rstrip(":")
            # Sum all CPU columns (varies by system)
            try:
                counts = [int(p) for p in parts[1:] if p.isdigit()]
                result[irq_id] = sum(counts)
            except (ValueError, IndexError):
                continue
        return result

    try:
        before = parse_interrupts()
        time.sleep(duration_secs)
        after = parse_interrupts()

        rates = {}
        total = 0
        for irq_id in after:
            if irq_id in before:
                delta = after[irq_id] - before[irq_id]
                if delta > 0:
                    rates[irq_id] = delta / duration_secs
                    total += delta

        return IrqRates(
            irq_rates=rates,
            duration_secs=duration_secs,
            total_interrupts=total,
        )
    except (OSError, ValueError) as exc:
        logger.error("Failed to sample IRQ rates: %s", exc)
        return None


def check_ptp_offset(interface: Optional[str] = None) -> Optional[PtpStatus]:
    """Check PTP synchronization status using pmc or phc_ctl.

    Args:
        interface: PTP interface to check (None = auto-detect)

    Returns:
        PtpStatus with offset/jitter info, or None if PTP not available
    """
    # Try pmc (PTP management client) first
    pmc = shutil.which("pmc")
    if pmc:
        try:
            result = subprocess.run(
                [pmc, "-u", "-b", "0", "GET CURRENT_DATA_SET"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                status = PtpStatus(interface=interface)
                # Parse pmc output for offset
                for line in result.stdout.splitlines():
                    if "offsetFromMaster" in line:
                        # Format: offsetFromMaster 123
                        match = re.search(r"offsetFromMaster\s+(-?\d+)", line)
                        if match:
                            status.offset_ns = float(match.group(1))
                if status.offset_ns is not None:
                    return status
        except (subprocess.TimeoutExpired, OSError):
            pass

    # Try phc_ctl as fallback
    phc_ctl = shutil.which("phc_ctl")
    if phc_ctl and interface:
        try:
            # Get PHC device for interface
            phc_path = Path(f"/sys/class/net/{interface}/device/ptp")
            if phc_path.exists():
                phc_devs = list(phc_path.iterdir())
                if phc_devs:
                    phc_dev = f"/dev/{phc_devs[0].name}"
                    result = subprocess.run(
                        [phc_ctl, phc_dev, "get"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        return PtpStatus(
                            interface=interface,
                            clock_state="available",
                        )
        except (subprocess.TimeoutExpired, OSError):
            pass

    return None


def get_nic_stats_delta(
    interfaces: List[str],
    duration_secs: int = 5,
) -> List[NicStats]:
    """Get NIC statistics delta over a measurement period.

    Args:
        interfaces: List of interface names to measure
        duration_secs: Time between samples

    Returns:
        List of NicStats with packet/error deltas
    """

    def read_stat(interface: str, stat: str) -> int:
        """Read a single sysfs statistic."""
        path = Path(f"/sys/class/net/{interface}/statistics/{stat}")
        try:
            return int(path.read_text().strip())
        except (OSError, ValueError):
            return 0

    def read_all_stats(interface: str) -> Dict[str, int]:
        """Read all relevant stats for an interface."""
        return {
            "rx_packets": read_stat(interface, "rx_packets"),
            "tx_packets": read_stat(interface, "tx_packets"),
            "rx_errors": read_stat(interface, "rx_errors"),
            "tx_errors": read_stat(interface, "tx_errors"),
            "rx_dropped": read_stat(interface, "rx_dropped"),
            "tx_dropped": read_stat(interface, "tx_dropped"),
        }

    # Take before snapshot
    before = {iface: read_all_stats(iface) for iface in interfaces}
    time.sleep(duration_secs)
    after = {iface: read_all_stats(iface) for iface in interfaces}

    results = []
    for iface in interfaces:
        if iface in before and iface in after:
            results.append(
                NicStats(
                    interface=iface,
                    rx_packets=after[iface]["rx_packets"]
                    - before[iface]["rx_packets"],
                    tx_packets=after[iface]["tx_packets"]
                    - before[iface]["tx_packets"],
                    rx_errors=after[iface]["rx_errors"]
                    - before[iface]["rx_errors"],
                    tx_errors=after[iface]["tx_errors"]
                    - before[iface]["tx_errors"],
                    rx_dropped=after[iface]["rx_dropped"]
                    - before[iface]["rx_dropped"],
                    tx_dropped=after[iface]["tx_dropped"]
                    - before[iface]["tx_dropped"],
                    duration_secs=duration_secs,
                )
            )

    return results


def run_validation_hook(
    phase: str,
    cfg: Dict,
    snapshot: Dict,
    output_dir: Optional[Path] = None,
    quick: bool = False,
) -> ValidationResult:
    """Run all validation hooks and collect results.

    Args:
        phase: "pre" or "post" to indicate when this is run
        cfg: The tuning configuration
        snapshot: System snapshot
        output_dir: Directory to write results (optional)
        quick: If True, use shorter measurement durations

    Returns:
        ValidationResult with all collected data
    """
    from datetime import datetime, timezone

    duration = 3 if quick else 10
    result = ValidationResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        phase=phase,
    )

    # Get CPU list for cyclictest from isolated cores config
    iso_cores = cfg.get("cpu", {}).get("isolate_cores", "")
    cpus = None
    if iso_cores and "TODO" not in str(iso_cores):
        try:
            cpus = _parse_cpulist(str(iso_cores))
        except Exception:
            pass

    # Run cyclictest
    try:
        result.latency = run_cyclictest(duration_secs=duration, cpus=cpus)
    except Exception as exc:
        result.errors.append(f"cyclictest failed: {exc}")

    # Sample IRQ rates
    try:
        result.irq_rates = sample_irq_rates(duration_secs=duration)
    except Exception as exc:
        result.errors.append(f"IRQ sampling failed: {exc}")

    # Check PTP status
    ptp_cfg = cfg.get("time_sync", {}).get("ptp", {})
    ptp_iface = ptp_cfg.get("interface") if isinstance(ptp_cfg, dict) else None
    if ptp_iface and "TODO" not in str(ptp_iface):
        try:
            result.ptp_status = check_ptp_offset(interface=ptp_iface)
        except Exception as exc:
            result.errors.append(f"PTP check failed: {exc}")

    # Get NIC stats
    interfaces = [
        e.get("name")
        for e in cfg.get("network", {}).get("interfaces", [])
        if e.get("name") and "TODO" not in str(e.get("name"))
    ]
    if not interfaces:
        interfaces = [
            n.get("name") for n in snapshot.get("nics", []) if n.get("name")
        ]

    if interfaces:
        try:
            result.nic_stats = get_nic_stats_delta(
                interfaces, duration_secs=duration
            )
        except Exception as exc:
            result.errors.append(f"NIC stats failed: {exc}")

    # Write results to file if output_dir specified
    if output_dir:
        output_file = output_dir / f"validation_{phase}.json"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file.write_text(json.dumps(result.to_dict(), indent=2))
            logger.info("Validation results written to %s", output_file)
        except OSError as exc:
            result.errors.append(f"Failed to write results: {exc}")

    return result


def _parse_cpulist(text: str) -> List[int]:
    """Parse a CPU list string like '0-3,8-11' into a list of integers.

    Wrapper around utils.parse_cpulist with graceful error handling.
    """
    try:
        return _utils_parse_cpulist(text)
    except ValueError as e:
        logger.warning("Invalid CPU list %r: %s", text, e)
        return []


def compare_validation_results(
    pre: ValidationResult,
    post: ValidationResult,
) -> Dict[str, str]:
    """Compare pre and post validation results and generate summary.

    Args:
        pre: Validation results from before tuning
        post: Validation results from after tuning

    Returns:
        Dictionary with comparison summary
    """
    summary = {}

    # Compare latency
    if pre.latency and post.latency:
        if pre.latency.max_us and post.latency.max_us:
            delta = post.latency.max_us - pre.latency.max_us
            pct = (
                (delta / pre.latency.max_us * 100) if pre.latency.max_us else 0
            )
            if delta < 0:
                summary["latency_max"] = (
                    f"Improved by {
                        abs(delta):.1f}us ({
                        abs(pct):.1f}%)"
                )
            else:
                summary["latency_max"] = (
                    f"Degraded by {
                        delta:.1f}us ({
                        pct:.1f}%)"
                )

        if pre.latency.avg_us and post.latency.avg_us:
            delta = post.latency.avg_us - pre.latency.avg_us
            pct = (
                (delta / pre.latency.avg_us * 100) if pre.latency.avg_us else 0
            )
            if delta < 0:
                summary["latency_avg"] = (
                    f"Improved by {
                        abs(delta):.1f}us ({
                        abs(pct):.1f}%)"
                )
            else:
                summary["latency_avg"] = (
                    f"Degraded by {
                        delta:.1f}us ({
                        pct:.1f}%)"
                )

    # Compare IRQ rates
    if pre.irq_rates and post.irq_rates:
        pre_total = pre.irq_rates.total_interrupts
        post_total = post.irq_rates.total_interrupts
        if pre_total and post_total:
            delta = post_total - pre_total
            pct = (delta / pre_total * 100) if pre_total else 0
            summary["irq_total"] = (
                f"Changed by {
                    delta:+d} interrupts ({
                    pct:+.1f}%)"
            )

    # Check for errors/drops
    for pre_stat, post_stat in zip(pre.nic_stats, post.nic_stats):
        if pre_stat.interface == post_stat.interface:
            if post_stat.rx_dropped > pre_stat.rx_dropped:
                summary[f"{pre_stat.interface}_rx_dropped"] = (
                    f"Warning: RX drops increased ({post_stat.rx_dropped - pre_stat.rx_dropped})"
                )
            if post_stat.rx_errors > pre_stat.rx_errors:
                summary[f"{pre_stat.interface}_rx_errors"] = (
                    f"Warning: RX errors increased ({post_stat.rx_errors - pre_stat.rx_errors})"
                )

    return summary
