# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Persistence artifact generation for LLTune."""

from __future__ import annotations

import logging
import shlex
from pathlib import Path
from typing import Dict, List, Tuple

from .utils import parse_cpulist, validate_interface_name

logger = logging.getLogger(__name__)

NIC_SERVICE_NAME = "lltune-nic-restore.service"
THP_SERVICE_NAME = "lltune-thp-setup.service"
IRQ_SERVICE_NAME = "lltune-irq-affinity.service"
WORKQUEUE_SERVICE_NAME = "lltune-workqueue.service"
LIMITS_CONF_NAME = "99-lltune.conf"
README_NAME = "README.txt"


def _write_file(path: Path, content: str, mode: int = 0o644) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(mode)
    return path


def _render_readme(bundle_root: Path) -> str:
    return (
        "LLTune persistence artifacts\n"
        "============================\n"
        f"Bundle root: {bundle_root}\n\n"
        "These files are staged only; they are not installed automatically.\n"
        "To persist NIC/THP tuning across reboot, copy the .service files to\n"
        "/etc/systemd/system/ and enable them, keeping scripts\n"
        "co-located under the same bundle path.\n\n"
        "Example:\n"
        f"  sudo cp {bundle_root / NIC_SERVICE_NAME} /etc/systemd/system/\n"
        f"  sudo cp {bundle_root / THP_SERVICE_NAME} /etc/systemd/system/\n"
        f"  sudo cp {bundle_root / WORKQUEUE_SERVICE_NAME} "
        "/etc/systemd/system/\n"
        "  sudo systemctl daemon-reload\n"
        f"  sudo systemctl enable {NIC_SERVICE_NAME} "
        f"{THP_SERVICE_NAME} {WORKQUEUE_SERVICE_NAME}\n\n"
        "For resource limits (memlock, nofile, nproc):\n"
        f"  sudo cp {bundle_root / LIMITS_CONF_NAME} /etc/security/limits.d/\n"
        "  # Log out and back in for limits to take effect\n\n"
        "Workqueue isolation (RHEL 9 Real-Time recommended):\n"
        "  The workqueue-isolate.sh script moves kernel workqueues and\n"
        "  threads off isolated CPUs. Set LLTUNE_HOUSEKEEPING_CPUS=0,1\n"
        "  before running\n"
        "  to specify which CPUs should handle housekeeping tasks.\n\n"
        "To rollback, disable and remove the units and re-enable any vendor\n"
        "tools as needed. The scripts remain in the bundle for reference."
    )


def _render_nic_service(script_path: Path) -> str:
    return (
        "[Unit]\n"
        "Description=Re-apply LLTune NIC settings\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={script_path}\n"
        "RemainAfterExit=yes\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _render_thp_service(script_path: Path) -> str:
    return (
        "[Unit]\n"
        "Description=Configure LLTune THP and hugepages\n"
        "DefaultDependencies=no\n"
        "After=local-fs.target\n"
        "Before=basic.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={script_path}\n"
        "RemainAfterExit=yes\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _render_nic_script(cfg: Dict, snapshot: Dict) -> str:
    """Render NIC tuning script with proper input validation."""
    network = cfg.get("network", {}) or {}
    defaults = network.get("defaults", {}) or {}
    interfaces_cfg = network.get("interfaces", []) or []

    # Build interface config mapping with validation
    interface_settings: Dict[str, Dict] = {}
    for entry in interfaces_cfg:
        name = entry.get("name")
        if name and validate_interface_name(name):
            interface_settings[name] = entry
        elif name:
            logger.warning("Skipping invalid interface name: %s", name)

    interfaces = list(interface_settings.keys())
    if not interfaces:
        interfaces = [
            nic.get("name")
            for nic in snapshot.get("nics", []) or []
            if nic.get("name") and validate_interface_name(nic.get("name"))
        ]

    offloads = []
    for key, flag in (
        ("disable_gro", "gro"),
        ("disable_lro", "lro"),
        ("disable_tso", "tso"),
        ("disable_gso", "gso"),
    ):
        if defaults.get(key) is True:
            offloads.append(flag)

    header = (
        "#!/bin/bash\n"
        "set -euo pipefail\n\n"
        'ETHTOOL_BIN="${ETHTOOL_BIN:-$(command -v ethtool || true)}"\n'
        'if [[ -z "$ETHTOOL_BIN" ]]; then\n'
        '  echo "ethtool not available; skipping NIC persistence" >&2\n'
        "  exit 0\n"
        "fi\n\n"
    )

    body_lines: List[str] = []

    # Per-interface function
    for nic in sorted(interfaces):
        settings = interface_settings.get(nic, {})
        body_lines.append(
            f"apply_{
                nic.replace(
                    '-',
                    '_').replace(
                    '.',
                    '_')}() {{"
        )
        body_lines.append(f'  local dev="{nic}"')
        body_lines.append('  if [[ ! -d "/sys/class/net/${dev}" ]]; then')
        body_lines.append(f'    echo "skip {nic}: interface missing" >&2')
        body_lines.append("    return")
        body_lines.append("  fi")

        # Offloads
        if offloads:
            flags = " ".join(f"{flag} off" for flag in offloads)
            body_lines.append(
                f'  $ETHTOOL_BIN -K "$dev" {flags} || echo "warn: ethtool -K on $dev failed" >&2'
            )

        # Coalescing
        coalesce = settings.get("coalescing", {}) or {}
        coal_args = []
        key_map = {
            "rx_usecs": "rx-usecs",
            "tx_usecs": "tx-usecs",
            "rx_frames": "rx-frames",
            "tx_frames": "tx-frames",
        }
        for key, ethtool_key in key_map.items():
            if key in coalesce:
                coal_args.append(f"{ethtool_key} {coalesce[key]}")
        if coal_args:
            body_lines.append(
                f'  $ETHTOOL_BIN -C "$dev" {
                    " ".join(coal_args)} || echo "warn: ethtool -C on $dev failed" >&2'
            )

        # Ring sizes
        rings = settings.get("rings", {}) or {}
        ring_args = []
        for key in ("rx", "tx"):
            if key in rings:
                ring_args.append(f"{key} {rings[key]}")
        if ring_args:
            body_lines.append(
                f'  $ETHTOOL_BIN -G "$dev" {
                    " ".join(ring_args)} || echo "warn: ethtool -G on $dev failed" >&2'
            )

        # Flow control
        flow = settings.get("flow_control", {}) or {}
        flow_args = []
        for key in ("rx", "tx"):
            if key in flow:
                flow_args.append(f"{key} {'on' if flow[key] else 'off'}")
        if flow_args:
            body_lines.append(
                f'  $ETHTOOL_BIN -A "$dev" {
                    " ".join(flow_args)} || echo "warn: ethtool -A on $dev failed" >&2'
            )

        # Queue configuration
        queues = settings.get("queues", {}) or {}
        queue_args = []
        for key in ("combined", "rx", "tx"):
            if key in queues:
                queue_args.append(f"{key} {queues[key]}")
        if queue_args:
            body_lines.append(
                f'  $ETHTOOL_BIN -L "$dev" {
                    " ".join(queue_args)} || echo "warn: ethtool -L on $dev failed" >&2'
            )

        body_lines.append("}\n")

    # Main execution
    body_lines.append("# Apply settings for all configured interfaces")
    for nic in sorted(interfaces):
        body_lines.append(f"apply_{nic.replace('-', '_').replace('.', '_')}")

    return header + "\n".join(body_lines) + "\n"


def _render_irq_service(script_path: Path) -> str:
    return (
        "[Unit]\n"
        "Description=Re-apply LLTune IRQ affinity settings\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={script_path}\n"
        "RemainAfterExit=yes\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _render_irq_script(cfg: Dict) -> str:
    """Generate a script to re-apply IRQ affinity settings at boot."""
    irq_cfg = cfg.get("irq", {}) or {}
    manual = irq_cfg.get("manual_affinity", []) or []
    try:
        avoid = set(parse_cpulist(str(irq_cfg.get("avoid_cores_for_irqs", ""))))
    except ValueError:
        avoid = set()

    header = (
        "#!/bin/bash\n"
        "set -euo pipefail\n\n"
        "# IRQ affinity persistence script generated by lltune\n"
        "# This script reads /proc/interrupts and applies affinity based on pattern matching.\n\n"
    )

    if not manual:
        return header + 'echo "No IRQ affinity rules configured"\n'

    body_lines: List[str] = []
    body_lines.append("# Apply affinity rules (using smp_affinity_list)")
    body_lines.append("apply_irq_affinity() {")
    body_lines.append('  local pattern="$1"')
    body_lines.append('  local cpulist="$2"')
    body_lines.append("")
    body_lines.append("  while IFS=: read -r irq_num rest; do")
    body_lines.append("    irq_num=$(echo \"$irq_num\" | tr -d ' ')")
    body_lines.append('    [[ "$irq_num" =~ ^[0-9]+$ ]] || continue')
    body_lines.append("    desc=$(echo \"$rest\" | awk '{print $NF}')")
    body_lines.append('    if [[ "$desc" == $pattern ]]; then')
    body_lines.append(
        '      echo "Setting IRQ $irq_num ($desc) -> $cpulist"'
    )
    body_lines.append(
        '      echo "$cpulist" > "/proc/irq/${irq_num}/smp_affinity_list" 2>/dev/null || \\'
    )
    body_lines.append(
        '        echo "warn: failed to set affinity for IRQ $irq_num" >&2'
    )
    body_lines.append("    fi")
    body_lines.append("  done < /proc/interrupts")
    body_lines.append("}\n")

    # Generate calls for each rule
    for rule in manual:
        pattern = rule.get("match", "")
        cpus = rule.get("cpus", [])
        if not pattern or not cpus:
            continue
        # Convert cpus to a concrete list and apply avoid_cores_for_irqs
        cpus_list: List[int] = []
        if isinstance(cpus, str):
            try:
                cpus_list = parse_cpulist(cpus)
            except ValueError:
                cpus_list = []
        elif isinstance(cpus, list):
            for c in cpus:
                try:
                    cpus_list.append(int(c))
                except (TypeError, ValueError):
                    continue

        if avoid:
            cpus_list = [c for c in cpus_list if c not in avoid]
        cpus_list = sorted(set(cpus_list))
        if not cpus_list:
            continue
        cpulist = ",".join(str(c) for c in cpus_list)
        # Use shlex.quote() for proper shell escaping (prevents injection)
        pattern_escaped = shlex.quote(pattern)
        cpulist_escaped = shlex.quote(cpulist)
        body_lines.append(
            f'apply_irq_affinity {pattern_escaped} {cpulist_escaped}'
        )

    return header + "\n".join(body_lines) + "\n"


def _render_workqueue_service(script_path: Path) -> str:
    return (
        "[Unit]\n"
        "Description=Move kernel workqueues off isolated CPUs\n"
        "After=multi-user.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={script_path}\n"
        "RemainAfterExit=yes\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _render_workqueue_script(cfg: Dict) -> str:
    """Generate script to move kernel workqueues and threads off isolated CPUs.

    Based on RHEL 9 Real-Time tuning recommendations.
    """
    cpu_cfg = cfg.get("cpu", {}) or {}
    kernel_cfg = cfg.get("kernel", {}) or {}
    cmdline = kernel_cfg.get("cmdline", {}) or {}

    # Get isolated cores from config
    isolated = cpu_cfg.get("isolate_cores", "") or cmdline.get("isolcpus", "")
    # Handle managed_irq,domain, prefix in isolcpus
    if "," in str(isolated) and not str(isolated)[0].isdigit():
        # isolcpus=managed_irq,domain,2-7 -> extract 2-7
        parts = str(isolated).split(",")
        for part in parts:
            if part and part[0].isdigit():
                isolated = part
                break

    header = (
        "#!/bin/bash\n"
        "set -euo pipefail\n\n"
        "# Move kernel workqueues and threads off isolated CPUs\n"
        "# Generated by lltune based on RHEL 9 Real-Time recommendations\n\n"
    )

    lines: List[str] = []

    lines.append("# Housekeeping CPUs (non-isolated)")
    lines.append('HOUSEKEEPING_CPUS="${LLTUNE_HOUSEKEEPING_CPUS:-0}"')
    lines.append("")

    lines.append("# Python interpreter for cpumask calculations")
    lines.append(
        'PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python || true)}"'
    )
    lines.append('if [[ -z "$PYTHON_BIN" ]]; then')
    lines.append(
        '  echo "python3 not available; skipping workqueue isolation" >&2'
    )
    lines.append("  exit 0")
    lines.append("fi")
    lines.append("")

    lines.append("# Convert housekeeping CPU list to hex mask (supports >64 CPUs)")
    lines.append("cpulist_to_mask() {")
    lines.append('  local list="$1"')
    lines.append('  "$PYTHON_BIN" - "$list" <<\'PY\'')
    lines.append("import sys")
    lines.append("")
    lines.append("text = sys.argv[1] if len(sys.argv) > 1 else \"\"")
    lines.append("cpus = set()")
    lines.append("for part in text.split(\",\"):")
    lines.append("    part = part.strip()")
    lines.append("    if not part:")
    lines.append("        continue")
    lines.append("    if \"-\" in part:")
    lines.append("        start_s, end_s = part.split(\"-\", 1)")
    lines.append("        start = int(start_s)")
    lines.append("        end = int(end_s)")
    lines.append("        if start > end:")
    lines.append("            raise SystemExit(1)")
    lines.append("        for cpu in range(start, end + 1):")
    lines.append("            if cpu >= 0:")
    lines.append("                cpus.add(cpu)")
    lines.append("    else:")
    lines.append("        cpu = int(part)")
    lines.append("        if cpu >= 0:")
    lines.append("            cpus.add(cpu)")
    lines.append("")
    lines.append("if not cpus:")
    lines.append("    print(\"0\")")
    lines.append("    raise SystemExit(0)")
    lines.append("")
    lines.append("max_cpu = max(cpus)")
    lines.append("nwords = max_cpu // 32 + 1")
    lines.append("words = [0] * nwords")
    lines.append("for cpu in cpus:")
    lines.append("    words[cpu // 32] |= 1 << (cpu % 32)")
    lines.append("print(\",\".join(f\"{w:08x}\" for w in reversed(words)))")
    lines.append("PY")
    lines.append("}")
    lines.append("")

    lines.append('HOUSEKEEPING_MASK=$(cpulist_to_mask "$HOUSEKEEPING_CPUS")')
    lines.append("")

    lines.append("# Move workqueues to housekeeping CPUs")
    lines.append("echo 'Moving workqueues to housekeeping CPUs...'")
    lines.append("for wq in /sys/devices/virtual/workqueue/*/cpumask; do")
    lines.append('  if [[ -w "$wq" ]]; then')
    lines.append('    echo "$HOUSEKEEPING_MASK" > "$wq" 2>/dev/null || true')
    lines.append("  fi")
    lines.append("done")
    lines.append("")

    lines.append("# Move kernel threads (kthreads) to housekeeping CPUs")
    lines.append("# This requires tuna or manual taskset")
    lines.append("if command -v tuna &>/dev/null; then")
    lines.append('  echo "Using tuna to move kernel threads..."')
    if isolated:
        lines.append(f"  tuna --cpus={isolated} --isolate 2>/dev/null || true")
    else:
        lines.append("  # No isolated cores configured")
    lines.append("else")
    lines.append('  echo "Moving kernel threads via taskset..."')
    lines.append("  # Move all kthreads (children of PID 2) to CPU 0")
    lines.append("  for pid in $(pgrep -P 2 2>/dev/null); do")
    lines.append(
        '    taskset -p -c "$HOUSEKEEPING_CPUS" "$pid" 2>/dev/null || true'
    )
    lines.append("  done")
    lines.append("fi")
    lines.append("")

    lines.append("# Move RCU threads to housekeeping CPUs")
    lines.append('for pid in $(pgrep "rcu[^c]" 2>/dev/null); do')
    lines.append(
        '  taskset -p -c "$HOUSEKEEPING_CPUS" "$pid" 2>/dev/null || true'
    )
    lines.append("done")
    lines.append("")

    lines.append('echo "Workqueue and kthread migration complete"')
    lines.append("")

    return header + "\n".join(lines)


def _render_limits_conf(memory_cfg: Dict) -> str:
    """Generate /etc/security/limits.d/99-lltune.conf content.

    Args:
        memory_cfg: Memory configuration section from config

    Returns:
        Limits conf file content
    """
    mlock = memory_cfg.get("mlock", {}) or {}
    limits = memory_cfg.get("limits", {}) or {}

    lines = [
        "# LLTune resource limits configuration",
        "# Generated by lltune - place in /etc/security/limits.d/",
        "#",
        "# Format: <domain> <type> <item> <value>",
        "# domain: * (all users), @group, or username",
        "# type: soft, hard, or - (both)",
        "#",
    ]

    # Get user/domain (default to all users)
    user = mlock.get("user", "*")

    # Memory locking limits
    if mlock.get("enabled", False) or mlock.get("soft") or mlock.get("hard"):
        memlock_soft = mlock.get("soft", "unlimited")
        memlock_hard = mlock.get("hard", "unlimited")
        lines.append("")
        lines.append(
            "# Memory locking - allows applications to lock memory (prevent swapping)"
        )
        if memlock_soft == memlock_hard:
            lines.append(f"{user}    -    memlock    {memlock_soft}")
        else:
            lines.append(f"{user}    soft    memlock    {memlock_soft}")
            lines.append(f"{user}    hard    memlock    {memlock_hard}")

    # File descriptor limits
    nofile = limits.get("nofile")
    if nofile:
        lines.append("")
        lines.append(
            "# File descriptors - increase for high-connection workloads"
        )
        lines.append(f"{user}    -    nofile    {nofile}")

    # Process limits
    nproc = limits.get("nproc")
    if nproc:
        lines.append("")
        lines.append(
            "# Process limit - increase for applications spawning many threads"
        )
        lines.append(f"{user}    -    nproc    {nproc}")

    # Real-time priority limits
    rtprio = limits.get("rtprio")
    if rtprio:
        lines.append("")
        lines.append(
            "# Real-time priority - allow applications to use SCHED_FIFO/SCHED_RR"
        )
        lines.append(f"{user}    -    rtprio    {rtprio}")

    # Stack size
    stack = limits.get("stack")
    if stack:
        lines.append("")
        lines.append(
            "# Stack size (KB) - increase for deeply recursive applications"
        )
        lines.append(f"{user}    -    stack    {stack}")

    lines.append("")
    return "\n".join(lines)


def _render_thp_script(memory_cfg: Dict) -> str:
    mode = str(memory_cfg.get("thp_runtime", "") or "")
    hugepages_cfg = memory_cfg.get("hugepages", {}) or {}
    size_kb = str(hugepages_cfg.get("size_kb", "") or "").strip()
    total = hugepages_cfg.get("total")
    per_node = {
        str(k): v for k, v in (hugepages_cfg.get("per_node", {}) or {}).items()
    }

    def _int_like(val) -> Tuple[bool, str]:
        try:
            return True, str(int(str(val).strip()))
        except (ValueError, TypeError):
            return False, ""

    header = "#!/bin/bash\nset -euo pipefail\n\n"
    lines: List[str] = []
    lines.append(f'mode="{mode}"')
    lines.append("thp_base=/sys/kernel/mm/transparent_hugepage")
    lines.append('if [[ -n "${mode:-}" ]] && [[ -d "$thp_base" ]]; then')
    lines.append(
        '  if [[ -w "$thp_base/enabled" ]]; then echo "$mode" > "$thp_base/enabled"; fi'
    )
    lines.append(
        '  if [[ -w "$thp_base/defrag" ]]; then echo "$mode" > "$thp_base/defrag"; fi'
    )
    lines.append("fi\n")

    if size_kb and (total or per_node):
        lines.append("hp_root=/sys/kernel/mm/hugepages")
        lines.append(f'hp_dir="$hp_root/hugepages-{size_kb}kB"')
        lines.append('if [[ -d "$hp_dir" ]]; then')
        ok, total_val = _int_like(total) if total is not None else (False, "")
        if ok:
            lines.append(
                f'  echo "{total_val}" > "$hp_dir/nr_hugepages" || '
                'echo "warn: hugepages total set failed" >&2'
            )
        lines.append("fi\n")
        if per_node:
            lines.append("for node in /sys/devices/system/node/node*; do")
            lines.append('  [[ -d "$node" ]] || continue')
            lines.append('  node_name=$(basename "$node")')
            lines.append('  case "$node_name" in')
            for node_name, count in sorted(per_node.items()):
                ok_node, count_val = _int_like(count)
                if not ok_node:
                    continue
                lines.append(
                    f'    {node_name}) echo "{count_val}" > '
                    f'"$node/hugepages/hugepages-{size_kb}kB/nr_hugepages" '
                    f'|| echo "warn: hugepages {node_name} failed" >&2 ;;'
                )
            lines.append("  esac")
            lines.append("done\n")

    return header + "\n".join(lines) + "\n"


def write_persistence_bundle(
    cfg: Dict, snapshot: Dict, bundle_root: Path
) -> Dict[str, Path]:
    """Stage persistence artifacts under bundle_root/persistence."""
    persistence_dir = bundle_root / "persistence"
    persistence_dir.mkdir(parents=True, exist_ok=True)

    nic_script_path = persistence_dir / "nic-restore.sh"
    thp_script_path = persistence_dir / "thp-setup.sh"
    irq_script_path = persistence_dir / "irq-affinity.sh"
    workqueue_script_path = persistence_dir / "workqueue-isolate.sh"
    limits_conf_path = persistence_dir / LIMITS_CONF_NAME

    _write_file(nic_script_path, _render_nic_script(cfg, snapshot), mode=0o755)
    _write_file(
        thp_script_path,
        _render_thp_script(cfg.get("memory", {}) or {}),
        mode=0o755,
    )
    _write_file(irq_script_path, _render_irq_script(cfg), mode=0o755)
    _write_file(
        workqueue_script_path, _render_workqueue_script(cfg), mode=0o755
    )
    _write_file(
        limits_conf_path, _render_limits_conf(cfg.get("memory", {}) or {})
    )

    _write_file(
        persistence_dir / NIC_SERVICE_NAME,
        _render_nic_service(nic_script_path),
    )
    _write_file(
        persistence_dir / THP_SERVICE_NAME,
        _render_thp_service(thp_script_path),
    )
    _write_file(
        persistence_dir / IRQ_SERVICE_NAME,
        _render_irq_service(irq_script_path),
    )
    _write_file(
        persistence_dir / WORKQUEUE_SERVICE_NAME,
        _render_workqueue_service(workqueue_script_path),
    )
    _write_file(persistence_dir / README_NAME, _render_readme(persistence_dir))

    return {
        "root": persistence_dir,
        "nic_service": persistence_dir / NIC_SERVICE_NAME,
        "thp_service": persistence_dir / THP_SERVICE_NAME,
        "irq_service": persistence_dir / IRQ_SERVICE_NAME,
        "workqueue_service": persistence_dir / WORKQUEUE_SERVICE_NAME,
        "nic_script": nic_script_path,
        "thp_script": thp_script_path,
        "irq_script": irq_script_path,
        "workqueue_script": workqueue_script_path,
        "limits_conf": limits_conf_path,
        "readme": persistence_dir / README_NAME,
    }
