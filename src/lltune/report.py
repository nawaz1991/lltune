# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Markdown report rendering."""

from __future__ import annotations

from typing import Dict, Optional, Sequence

from .version import __version__


def _fmt_bool(val: Optional[bool]) -> str:
    if val is True:
        return "yes"
    if val is False:
        return "no"
    return "unknown"


def render_markdown(
    snapshot: Dict,
    recommendations: Optional[Sequence] = None,
    reboot_required: bool = False,
) -> str:
    host = snapshot.get("host", {})
    cpu = snapshot.get("cpu", {})
    memory = snapshot.get("memory", {})
    services = snapshot.get("services", {})
    time_sync = snapshot.get("time_sync", {})

    lines = []
    lines.append("# LLTune Scan Report")
    lines.append("")
    lines.append(f"- Tool version: {__version__}")
    lines.append(f"- Host: {host.get('hostname', 'unknown')}")
    lines.append(
        f"- OS: {
            host.get(
                'os',
                {}).get(
                'name',
                'unknown')} {
                    host.get(
                        'os',
                        {}).get(
                            'version_id',
                        '')}".strip()
    )
    lines.append(f"- Kernel: {host.get('kernel', 'unknown')}")
    lines.append(f"- Collected at: {host.get('collected_at', '')}")
    lines.append(f"- Reboot required: {_fmt_bool(reboot_required)}")
    lines.append("")

    lines.append("## CPU & NUMA")
    sockets = cpu.get("sockets", 0)
    cores = cpu.get("cores_per_socket", 0)
    threads = cpu.get("threads_per_core", 0)
    lines.append(
        f"- Sockets: {sockets}, cores/socket: {cores}, threads/core: {threads}"
    )
    lines.append(f"- SMT: {_fmt_bool(cpu.get('smt_enabled'))}")
    lines.append(
        f"- Governors read: {len(cpu.get('per_cpu_governor', {}))} CPUs"
    )
    lines.append(
        f"- NUMA nodes: {len(snapshot.get('numa', {}).get('nodes', []))}"
    )
    lines.append("")

    lines.append("## Memory")
    lines.append(f"- Total: {memory.get('total_kb', 'n/a')} kB")
    lines.append(
        f"- THP: {
            memory.get(
                'thp_enabled',
                'unknown')} (defrag: {
            memory.get(
                'thp_defrag',
                'unknown')})"
    )
    lines.append(f"- Swap devices: {len(memory.get('swap_devices', []))}")
    lines.append(
        f"- NUMA balancing: {_fmt_bool(memory.get('numa_balancing'))}"
    )
    lines.append(f"- KSM: {_fmt_bool(memory.get('ksm_enabled'))}")
    lines.append("")

    lines.append("## NICs")
    for nic in snapshot.get("nics", []):
        lines.append(
            f"- {
                nic.get('name')}: vendor={
                nic.get('vendor')}, driver={
                nic.get('driver')}, speed={
                    nic.get(
                        'speed_mbps',
                        '?')} Mb/s, numa={
                            nic.get('numa_node')}"
        )
        lines.append(
            f"  - offloads: {', '.join(list(nic.get('offloads', {}).keys())[:4]) or 'n/a'}"
        )
        queues = nic.get("queues", {})
        lines.append(
            f"  - queues: rx={
                queues.get('rx_queues')}, tx={
                queues.get('tx_queues')}, combined={
                queues.get('combined')}, rps_flow_cnt={
                    queues.get('rps_flow_cnt')}"
        )
    lines.append("")

    lines.append("## Time & Services")
    lines.append(
        f"- irqbalance: {_fmt_bool(services.get('irqbalance_active'))}"
    )
    lines.append(
        f"- NTP: {
            _fmt_bool(
                time_sync.get('ntp_active'))}, chrony: {
            _fmt_bool(
                time_sync.get('chrony_active'))}, PTP: {
            _fmt_bool(
                time_sync.get('ptp_present'))}"
    )
    lines.append(
        f"- Clocksource: {
            time_sync.get(
                'clocksource',
                'unknown')} (TSC stable: {
            _fmt_bool(
                time_sync.get('tsc_stable'))})"
    )
    lines.append("")

    lines.append("## Recommendations")
    if recommendations:
        for rec in recommendations:
            # Convert Recommendation objects to dicts if needed
            if hasattr(rec, "to_dict") and callable(getattr(rec, "to_dict")):
                rec_dict = rec.to_dict()
            elif isinstance(rec, dict):
                rec_dict = rec
            else:
                # Fallback for unexpected types
                rec_dict = {
                    "category": "?",
                    "item": "?",
                    "rationale": str(rec),
                }

            category = rec_dict.get('category', '?')
            item = rec_dict.get('item', '?')
            current = rec_dict.get('current')
            target = rec_dict.get('target')
            impact = rec_dict.get('impact')
            rationale = rec_dict.get('rationale')
            lines.append(
                f"- [{category}] {item}: "
                f"current={current}, target={target}, "
                f"impact={impact}; {rationale}"
            )
    else:
        lines.append("- No recommendations generated.")

    return "\n".join(lines) + "\n"
