# LLTune - Low-Latency System Tuner

**Automated system tuning for High-Frequency Trading (HFT) and latency-sensitive workloads**

![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Version](https://img.shields.io/badge/version-0.1.1-green.svg)
![PyPI](https://img.shields.io/pypi/v/lltune.svg)

---

## Table of Contents

- [Overview](#overview)
- [Why LLTune?](#why-lltune)
- [What Does LLTune Tune?](#what-does-lltune-tune)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Configuration Reference](#configuration-reference)
- [Editing the Config File](#editing-the-config-file---best-practices)
- [Output Files](#output-files)
- [Persistence Across Reboots](#persistence-across-reboots)
- [User-Space Stacks](#user-space-stacks)
- [Recommendations System](#recommendations-system)
- [Safety Features](#safety-features)
- [Troubleshooting](#troubleshooting)
- [References](#references)

---

## Overview

LLTune is a comprehensive system tuning toolkit designed specifically for High-Frequency Trading (HFT) servers and other latency-sensitive workloads. It automates the discovery, analysis, and application of low-latency optimizations across CPU, memory, network, kernel, and IRQ subsystems.

**Target Audience:**
- HFT/Quantitative Trading Engineers
- System Administrators managing trading infrastructure
- Performance Engineers optimizing latency-critical applications
- DevOps teams deploying real-time systems

**Key Value Proposition:**
- Automated discovery of current system configuration
- Industry best-practice recommendations with impact and risk assessment
- Safe application of tuning with automatic backups and rollback capability
- Persistence across reboots via systemd services and kernel parameters

---

## Why LLTune?

### The Problem

Manual tuning of HFT servers is:

- **Error-prone**: Dozens of interdependent settings across CPU, memory, network, kernel, and IRQ subsystems
- **Time-consuming**: Hours of research and testing for each server
- **Expertise-intensive**: Requires deep knowledge of Linux internals, NUMA topology, and hardware specifics
- **Risky**: Incorrect settings can cause system instability or worse latency

### The Solution

LLTune provides:

1. **Automated Discovery**: Comprehensive scanning of CPU, memory, NICs, NUMA topology, IRQs, and services
2. **Smart Recommendations**: Best-practice suggestions with impact/risk assessment
3. **Safe Application**: Automatic backups, dry-run mode, and rollback capability
4. **Boot Persistence**: systemd services, GRUB configuration, and sysctl.d integration
5. **User-Space Stack Support**: Solarflare Onload, Mellanox VMA, and RDMA configuration

### Key Benefits

| Benefit | Description |
|---------|-------------|
| Comprehensive | Covers CPU, memory, network, kernel, IRQs, time sync, and user stacks |
| Safe | Automatic backups, dry-run mode, validation, and rollback |
| Persistent | Tuning survives reboots via systemd and GRUB |
| Documented | Every recommendation includes rationale and risk level |
| RHEL 9 Ready | Optimized for AlmaLinux 9, Rocky Linux 9, RHEL 9 |

---

## What Does LLTune Tune?

### Tuning Domains

| Domain | Settings |
|--------|----------|
| **CPU** | Governor (performance), turbo boost, C-states, core isolation, frequency scaling, EPP |
| **Memory** | Transparent Huge Pages (THP), hugepages allocation, swap, NUMA balancing, KSM, memory locking |
| **Network** | NIC offloads (GRO/LRO/TSO/GSO), coalescing, ring buffers, flow control, queues, sysctl tuning |
| **Kernel** | Boot parameters: `isolcpus`, `nohz_full`, `rcu_nocbs`, `kthread_cpus`, `irqaffinity`, mitigations |
| **IRQs** | Affinity pinning, RPS/RFS control, cross-NUMA detection |
| **Services** | irqbalance (disable), tuned profile management |
| **Time Sync** | NTP/Chrony/PTP validation, clocksource selection |
| **User Stacks** | Solarflare Onload (EF_*), Mellanox VMA (VMA_*), RDMA alignment |

### Kernel Parameters Configured

LLTune can configure these critical kernel boot parameters:

```
isolcpus=managed_irq,domain,<cores>   # CPU isolation with managed IRQ
nohz_full=<cores>                      # Adaptive-tick (tickless) mode
rcu_nocbs=<cores>                      # Offload RCU callbacks
kthread_cpus=<housekeeping>            # Pin kernel threads
irqaffinity=<housekeeping>             # Default IRQ affinity
skew_tick=1                            # Reduce timer tick jitter
tsc=reliable                           # Mark TSC as reliable
nosoftlockup                           # Disable soft lockup detector
nmi_watchdog=0                         # Disable NMI watchdog
transparent_hugepage=never             # Disable THP at boot
intel_pstate=disable                   # Use acpi-cpufreq (Intel)
processor.max_cstate=1                 # Limit C-states
idle=poll                              # Ultra-low latency (100% CPU)
mitigations=off                        # Disable CPU mitigations (risk!)
```

---

## Installation

### From PyPI (Recommended)

```bash
pip install lltune

# Verify installation
lltune --version
```

### From Source

```bash
# Clone the repository
git clone https://github.com/nawaz1991/lltune.git
cd lltune

# Install in development mode
pip install -e .

# Verify installation
lltune --version
```

### Alternative: Direct Execution

If pip installation has issues with sudo:

```bash
# Run directly with PYTHONPATH
sudo PYTHONPATH=src python -m lltune.cli <command>

# Or use the bin script
sudo PYTHONPATH=src ./bin/lltune <command>
```

### Requirements

- Python 3.9+
- Linux (tested on AlmaLinux 9.6, RHEL 9, Rocky Linux 9)
- Root privileges for `apply` and `rollback` commands
- Dependencies: `pyyaml`, `ruamel.yaml`

---

## Quick Start

### Complete Workflow

```bash
# Step 1: Scan the system and generate reports
sudo lltune scan --format yaml -o snapshot.yaml --md-report report.md

# Step 2: Generate configuration template from snapshot
lltune gen-config --snapshot snapshot.yaml -o config.yaml

# Step 3: Edit config.yaml to customize for your environment
#         (See "Editing the Config File" section below)
vim config.yaml

# Step 4: Validate configuration against schema and host
lltune audit -c config.yaml --snapshot snapshot.yaml

# Step 5: Preview changes without applying (dry-run)
lltune apply --plan -c config.yaml

# Step 6: Apply tuning (requires root)
sudo lltune apply -c config.yaml

# Step 7: Reboot if kernel parameters were changed
sudo reboot

# Step 8: Rollback if needed
sudo lltune rollback --backup /var/lib/lltune/backups/backup-<timestamp>/
```

### Minimal Example

```bash
# Quick scan and apply with defaults
sudo lltune scan -o snapshot.yaml
lltune gen-config --snapshot snapshot.yaml -o config.yaml
# Edit config.yaml...
sudo lltune apply -c config.yaml
```

---

## CLI Reference

### Global Options

```
--version              Show version and exit
--log-file PATH        Log file path (default: /var/log/lltune/lltune.log)
-v, --verbose          Increase verbosity
-q, --quiet            Reduce verbosity
```

### Commands

#### `lltune scan`

Discover current system state and generate recommendations.

```bash
lltune scan [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-o, --output PATH` | Output file path for snapshot |
| `--format {text,json,yaml}` | Output format (default: text) |
| `--md-report PATH` | Generate Markdown report |

**Examples:**

```bash
# Text summary to stdout
sudo lltune scan

# YAML snapshot with Markdown report
sudo lltune scan --format yaml -o snapshot.yaml --md-report report.md

# JSON format
sudo lltune scan --format json -o snapshot.json
```

**Output:**
- System state snapshot (CPU, memory, NICs, NUMA, IRQs, services)
- Tuning recommendations with impact/risk assessment

---

#### `lltune gen-config`

Generate a configuration template from a snapshot.

```bash
lltune gen-config [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-o, --output PATH` | Output file path for config |
| `--snapshot PATH` | Input snapshot file (optional; collects live if not provided) |

**Examples:**

```bash
# Generate from existing snapshot
lltune gen-config --snapshot snapshot.yaml -o config.yaml

# Generate from live system
lltune gen-config -o config.yaml
```

**Output:**
- YAML configuration file with:
  - Hardware information (read-only)
  - Tuning settings with TODO placeholders
  - Embedded recommendations

---

#### `lltune audit`

Validate a configuration file against schema and host capabilities.

```bash
lltune audit [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-c, --config PATH` | **(Required)** Config file to audit |
| `--snapshot PATH` | Snapshot for cross-validation |
| `--output PATH` | JSON output for validation issues |

**Examples:**

```bash
# Basic validation
lltune audit -c config.yaml

# With cross-validation against snapshot
lltune audit -c config.yaml --snapshot snapshot.yaml

# Output issues to JSON
lltune audit -c config.yaml --output issues.json
```

**Exit Codes:**
- `0`: No errors (warnings may be present)
- `1`: Errors found

---

#### `lltune apply`

Apply tuning configuration to the system.

```bash
lltune apply [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-c, --config PATH` | **(Required)** Config file to apply |
| `--plan` | Show plan without applying (dry-run) |
| `--validate` | Run pre/post validation (cyclictest) |
| `--quick-validate` | Use shorter validation durations |

**Examples:**

```bash
# Dry-run to see what would change
lltune apply --plan -c config.yaml

# Apply tuning (requires root)
sudo lltune apply -c config.yaml

# Apply with latency validation
sudo lltune apply -c config.yaml --validate
```

**Root Requirement:** Required unless `--plan` is specified.

**Output:**
- Backup bundle created at `/var/lib/lltune/backups/backup-<timestamp>/`
- Detailed log of applied changes
- Reboot requirement notification (if kernel parameters changed)

---

#### `lltune rollback`

Restore system to backed-up state.

```bash
lltune rollback [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--backup PATH` | **(Required)** Path to backup bundle |

**Examples:**

```bash
# Rollback from specific backup
sudo lltune rollback --backup /var/lib/lltune/backups/backup-20250101T120000/
```

**Actions Performed:**
1. Restore `/etc/default/grub`
2. Restore `/etc/sysctl.d/99-latency-tuner.conf`
3. Restore `/etc/fstab` (swap entries)
4. Regenerate GRUB configuration
5. Disable lltune systemd services
6. Reload sysctl settings

**Note:** Reboot required after rollback for kernel parameter changes.

---

## Configuration Reference

### Config File Structure

```yaml
version: 1                    # Schema version (required)

metadata:                     # Auto-generated (read-only)
  generated_at: "..."
  host: "hostname"
  kernel: "5.14.0-..."
  tool_version: "0.1.0"

hardware:                     # Discovered hardware (read-only)
  sockets: 2
  cores_per_socket: 28
  threads_per_core: 2
  numa_nodes: 2
  nics: [...]

cpu:                          # CPU tuning
  governor: { target: performance }
  isolate_cores: "1-27,57-83"
  turbo: false
  cstate_limit: 1

kernel:                       # Kernel boot parameters
  cmdline:
    isolcpus: "managed_irq,domain,1-27,57-83"
    nohz_full: "1-27,57-83"
    rcu_nocbs: "1-27,57-83"
    # ... more params

memory:                       # Memory tuning
  thp_runtime: never
  swap_disable: true
  numa_balancing: false
  hugepages: { ... }
  mlock: { ... }
  limits: { ... }

network:                      # Network tuning
  defaults: { ... }
  sysctl: { ... }
  interfaces: [ ... ]

irq:                          # IRQ affinity
  manual_affinity: [ ... ]
  avoid_cores_for_irqs: "..."

time_sync:                    # Time synchronization
  ntp: true
  ptp: { interface: "...", phc2sys: true }

services:                     # Service management
  irqbalance: false
  tuned: "latency-performance"

safety:                       # Safety guardrails
  allow_grub_edit: false
  allow_dangerous_mitigations: false

recommendations: [ ... ]      # Auto-generated recommendations
```

### Section Details

#### `cpu` Section

```yaml
cpu:
  governor:
    target: performance       # CPU frequency governor
  isolate_cores: "1-27,57-83" # CPUs to isolate from scheduler
  turbo: false                # Disable turbo boost for consistency
  cstate_limit: 1             # Max C-state (0=C0, 1=C1, etc.)
  epp: performance            # Energy Performance Preference
```

#### `kernel` Section

```yaml
kernel:
  cmdline:
    # CPU isolation (RHEL 9 style with managed_irq)
    isolcpus: "managed_irq,domain,1-27,57-83"
    nohz_full: "1-27,57-83"        # Adaptive-tick mode
    rcu_nocbs: "1-27,57-83"        # RCU callback offload

    # Kernel thread pinning
    kthread_cpus: "0,56"           # Pin kernel threads
    irqaffinity: "0,56"            # Default IRQ affinity

    # Timer and watchdog
    skew_tick: "1"                 # Reduce tick alignment jitter
    tsc: reliable                  # Trust TSC for timekeeping
    nosoftlockup: ""               # Disable soft lockup detector
    nmi_watchdog: "0"              # Disable NMI watchdog
    nowatchdog: ""                 # Disable watchdog

    # Memory
    transparent_hugepage: never    # Disable THP at boot

    # Power management
    intel_pstate: disable          # Use acpi-cpufreq instead
    processor.max_cstate: "1"      # Limit ACPI C-states
    idle: poll                     # Spin instead of halt (100% CPU!)

    # Security (DANGEROUS - requires safety flag)
    mitigations: off               # Disable CPU vulnerability mitigations
```

#### `memory` Section

```yaml
memory:
  thp_runtime: never           # THP: never, always, madvise
  swap_disable: true           # Disable swap devices
  numa_balancing: false        # Disable automatic NUMA balancing
  ksm: false                   # Disable Kernel Same-page Merging
  dirty_ratio: 10              # Max dirty page ratio (%)
  dirty_background_ratio: 5    # Background writeback threshold (%)
  stat_interval: 120           # VM stats collection interval (seconds)

  hugepages:
    size_kb: "2048"            # 2MB pages (or "1048576" for 1GB)
    total: 32768               # Total pages to allocate
    per_node:
      node0: 16384             # Pages on NUMA node 0
      node1: 16384             # Pages on NUMA node 1

  mlock:
    enabled: true
    user: "*"                  # All users (or specific username)
    soft: unlimited
    hard: unlimited
    max_map_count: 262144

  limits:
    nofile: 1048576            # Max open file descriptors
    nproc: 65536               # Max processes
    rtprio: 99                 # Max real-time priority
```

#### `network` Section

```yaml
network:
  defaults:
    disable_gro: true          # Generic Receive Offload
    disable_lro: true          # Large Receive Offload
    disable_tso: true          # TCP Segmentation Offload
    disable_gso: true          # Generic Segmentation Offload

  sysctl:
    # Buffer sizes (64MB)
    rmem_max: 67108864
    wmem_max: 67108864
    rmem_default: 67108864
    wmem_default: 67108864
    tcp_rmem: "4096 87380 67108864"
    tcp_wmem: "4096 65536 67108864"

    # Low latency TCP
    tcp_timestamps: false      # Disable for lower overhead
    tcp_sack: false            # Disable for predictable latency
    tcp_low_latency: true
    tcp_fastopen: 3
    tcp_tw_reuse: true
    tcp_fin_timeout: 15

    # Busy polling (critical for HFT)
    busy_poll: 50              # Microseconds
    busy_read: 50

    # Queue and backlog
    netdev_max_backlog: 250000
    netdev_budget: 600
    somaxconn: 65535
    file_max: 2097152

  interfaces:
    - name: ens3f0
      role: trading            # trading, control, management, multicast
      numa_node: 0
      coalescing:
        rx_usecs: 0
        tx_usecs: 0
      rings:
        rx: 4096
        tx: 2048
```

#### `irq` Section

```yaml
irq:
  manual_affinity:
    - match: "ens3f*"          # Glob pattern for IRQ names
      cpus: [0, 56]            # CPUs to pin to
    - match: "mlx5*"
      cpus: [28, 84]

  avoid_cores_for_irqs: "1-27,57-83"  # Never pin IRQs here
  disable_rps: true            # Disable Receive Packet Steering
  disable_rfs: true            # Disable Receive Flow Steering
```

#### `safety` Section

```yaml
safety:
  # Must be true to modify GRUB/kernel cmdline
  allow_grub_edit: false

  # Must be true to disable CPU vulnerability mitigations
  allow_dangerous_mitigations: false
```

---

## Editing the Config File - Best Practices

### Understanding Your Hardware

Before editing the config file, gather information about your system:

```bash
# NUMA topology
numactl --hardware
lscpu | grep NUMA

# CPU topology (cores, threads, sockets)
lscpu

# NIC NUMA placement
cat /sys/class/net/*/device/numa_node

# Thread siblings (HT pairs)
cat /sys/devices/system/cpu/cpu0/topology/thread_siblings_list
```

### Core Isolation Strategy

**Goal:** Isolate trading cores from OS interference while keeping housekeeping cores for system tasks.

**Best Practice:**

1. **Reserve housekeeping cores**: Typically CPU 0 and its HT sibling (e.g., CPU 56 on a 2-socket system)
2. **Isolate trading cores**: On the same NUMA node as your trading NICs
3. **Match all isolation parameters**: `isolate_cores`, `isolcpus`, `nohz_full`, `rcu_nocbs` should specify the same cores

**Example for dual-socket system:**

```yaml
# NUMA Node 0: CPUs 0-27, 56-83 (physical + HT siblings)
# NUMA Node 1: CPUs 28-55, 84-111

cpu:
  isolate_cores: "1-27,57-83"    # All of Node 0 except housekeeping

kernel:
  cmdline:
    isolcpus: "managed_irq,domain,1-27,57-83"
    nohz_full: "1-27,57-83"
    rcu_nocbs: "1-27,57-83"
    kthread_cpus: "0,56"          # Housekeeping cores
    irqaffinity: "0,56"
```

### Hugepages Calculation

**Formula:**
```
pages = desired_memory_bytes / (page_size_kb * 1024)
```

**Examples:**

| Desired Memory | Page Size | Pages Needed |
|----------------|-----------|--------------|
| 64 GB | 2 MB | 32,768 |
| 128 GB | 2 MB | 65,536 |
| 64 GB | 1 GB | 64 |

**Configuration:**

```yaml
memory:
  hugepages:
    size_kb: "2048"        # 2MB pages
    total: 32768           # 64GB total
    per_node:
      node0: 16384         # 32GB on Node 0
      node1: 16384         # 32GB on Node 1
```

**Tip:** Distribute hugepages evenly across NUMA nodes to ensure local memory access.

### NIC Role Assignment

| Role | Description | Typical NICs |
|------|-------------|--------------|
| `trading` | Ultra-low-latency market data/order paths | Solarflare, Mellanox |
| `control` | Management, monitoring, non-latency-critical | Intel igb, ixgbe |
| `management` | BMC, IPMI, SSH access | Onboard, USB |
| `multicast` | Market data multicast reception | Dedicated feed NICs |

**Example:**

```yaml
network:
  interfaces:
    - name: ens3f0
      role: trading
      numa_node: 0
    - name: enp152s0f0np0
      role: trading
      numa_node: 1
    - name: enp75s0f0
      role: control
      numa_node: 0
    - name: bond0
      role: management
```

### IRQ Affinity Strategy

**Rules:**

1. Pin NIC IRQs to **housekeeping cores** on the **same NUMA node** as the NIC
2. **Never** pin IRQs to isolated cores
3. Use glob patterns to match IRQ names

**Example:**

```yaml
irq:
  manual_affinity:
    # Solarflare NICs on Node 0 → housekeeping cores on Node 0
    - match: "ens3f*"
      cpus: [0, 56]

    # Mellanox NICs on Node 1 → housekeeping cores on Node 1
    - match: "enp152s0f*"
      cpus: [28, 84]

  # Must match isolated cores
  avoid_cores_for_irqs: "1-27,57-83"
```

### Safety Flags

**`allow_grub_edit`**: Required to modify kernel command line

```yaml
# Without this, kernel.cmdline changes are ignored
safety:
  allow_grub_edit: true
```

**`allow_dangerous_mitigations`**: Required to disable CPU mitigations

```yaml
# DANGEROUS: Disables Spectre/Meltdown protections
# Only enable if you understand the security implications
safety:
  allow_dangerous_mitigations: true

kernel:
  cmdline:
    mitigations: "off"
```

---

## Output Files

### snapshot.yaml

Complete system state discovery including:

- Host information (hostname, kernel, OS)
- CPU inventory (vendor, model, cores, governors)
- NUMA topology (nodes, CPUs, memory)
- Memory configuration (THP, hugepages, swap)
- NIC details (driver, firmware, offloads, queues, NUMA node)
- IRQ mappings and affinities
- Service status (irqbalance, tuned)
- Time synchronization status
- User stack versions (Onload, VMA)

**Usage:** Input for `gen-config` and `audit` commands.

### report.md

Human-readable Markdown report containing:

- System summary (CPU, memory, NICs)
- Service status
- Tuning recommendations with:
  - Category and item
  - Current vs. target values
  - Impact level (low/medium/high)
  - Rationale

**Usage:** Share with stakeholders or for documentation.

### config.yaml

Tuning configuration file with:

- Hardware information (read-only)
- Tuning settings (editable)
- Embedded recommendations

**Usage:** Edit and pass to `apply` command.

### Backup Bundle

Created by `apply` command at `/var/lib/lltune/backups/backup-<timestamp>/`:

```
backup-20250101T120000/
├── config.yaml              # Applied configuration
├── snapshot.json            # System state at apply time
├── baseline/                # Original files (for rollback)
│   ├── etc/
│   │   ├── default/grub
│   │   ├── sysctl.d/99-latency-tuner.conf
│   │   └── fstab
│   ├── boot/grub2/grub.cfg                      # if present
│   ├── boot/efi/EFI/<distro>/grub.cfg           # if present
│   └── ethtool/                                 # Per-NIC ethtool output
│       ├── ens3f0.features
│       ├── ens3f0.coalesce
│       ├── ens3f0.rings
│       ├── ens3f0.flowctrl
│       └── ...
└── persistence/                                 # Staged only (not installed)
    ├── nic-restore.sh
    ├── thp-setup.sh
    ├── irq-affinity.sh
    ├── workqueue-isolate.sh
    ├── 99-lltune.conf
    ├── lltune-nic-restore.service
    ├── lltune-thp-setup.service
    ├── lltune-irq-affinity.service
    ├── lltune-workqueue.service
    └── README.txt
```

**Usage:** Pass to `rollback` command to restore system.

---

## Persistence Across Reboots

### Automatic Persistence

These changes persist automatically:

| Setting | Persistence Mechanism |
|---------|----------------------|
| Kernel parameters | `/etc/default/grub` + `grub2-mkconfig` |
| Sysctl settings | `/etc/sysctl.d/99-latency-tuner.conf` |
| Swap disable | `/etc/fstab` modification |

### Manual Persistence (systemd Services)

These settings require manual installation of systemd services:

| Setting | Service |
|---------|---------|
| NIC offloads, coalescing, rings | `lltune-nic-restore.service` |
| THP disable, hugepages | `lltune-thp-setup.service` |
| IRQ affinity | `lltune-irq-affinity.service` |
| Workqueue isolation | `lltune-workqueue.service` |

**Installation:**

```bash
# Copy service units (ExecStart points into the backup bundle)
sudo cp /var/lib/lltune/backups/backup-*/persistence/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable only the services you want
sudo systemctl enable --now lltune-nic-restore lltune-thp-setup lltune-irq-affinity
# Optional:
sudo systemctl enable --now lltune-workqueue

# Resource limits (memlock/nofile/nproc/rtprio)
sudo cp /var/lib/lltune/backups/backup-*/persistence/99-lltune.conf /etc/security/limits.d/
# Log out/in for limits to take effect

# IMPORTANT: these units reference scripts under the backup bundle path;
# keep that bundle path intact or edit ExecStart to point to a stable location.

# Verify
sudo systemctl list-unit-files | grep lltune
```

---

## User-Space Stacks

### Solarflare Onload

LLTune generates environment profiles for Solarflare Onload:

```yaml
onload:
  generate_profile: true
  tuning_level: ultra_low_latency  # or low_latency, balanced
```

**Generated Profile:** `/etc/profile.d/lltune-onload.sh`

**Key Variables:**
- `EF_POLL_USEC=0` - Adaptive busy polling
- `EF_INT_DRIVEN=0` - Spinning mode
- `EF_SPIN_USEC=-1` - Infinite spin
- `EF_HIGH_THROUGHPUT_MODE=0` - Latency optimized

**Usage:**

```bash
source /etc/profile.d/lltune-onload.sh
onload ./your_trading_app
```

### Mellanox VMA

LLTune generates environment profiles for Mellanox VMA:

```yaml
vma:
  generate_profile: true
  tuning_level: ultra_low_latency
```

**Generated Profile:** `/etc/profile.d/lltune-vma.sh`

**Key Variables:**
- `VMA_SPEC=latency` - Latency profile
- `VMA_RX_POLL=-1` - Infinite polling
- `VMA_THREAD_MODE=1` - Multi-threaded
- `VMA_BF=1` - Blue Flame enabled

**Usage:**

```bash
source /etc/profile.d/lltune-vma.sh
LD_PRELOAD=libvma.so ./your_trading_app
```

### RDMA Alignment

LLTune validates RDMA device NUMA alignment:

```bash
# Check in recommendations
lltune scan --format yaml -o snapshot.yaml
grep -A5 "rdma" snapshot.yaml
```

---

## Recommendations System

### Categories

| Category | Description |
|----------|-------------|
| `cpu` | Governor, SMT, turbo, C-states |
| `kernel` | Boot parameters, isolation |
| `memory` | THP, hugepages, swap, NUMA |
| `network` | Sysctl tuning |
| `nic` | Per-NIC offloads, coalescing, rings |
| `irq` | Affinity, cross-NUMA issues |
| `services` | irqbalance, tuned |
| `limits` | memlock, nofile, nproc |
| `time` | Clocksource, NTP/PTP |

### Severity Levels

| Level | Meaning |
|-------|---------|
| `info` | Informational; optional optimization |
| `warning` | Recommended change; may impact latency |
| `error` | Critical issue; should be addressed |

### Impact Levels

| Level | Meaning |
|-------|---------|
| `low` | Minor latency improvement |
| `medium` | Noticeable latency improvement |
| `high` | Significant latency improvement |

### Risk Levels

| Level | Meaning |
|-------|---------|
| `safe` | No system impact beyond target |
| `potentially_disruptive` | May affect other workloads |
| `high_risk` | May cause instability or security concerns |

---

## Safety Features

### Automatic Backups

Every `apply` command creates a timestamped backup bundle containing:
- Applied configuration
- Original system files
- Persistence scripts

### Dry-Run Mode

Preview changes without applying:

```bash
lltune apply --plan -c config.yaml
```

### Validation

Schema and cross-validation before apply:

```bash
lltune audit -c config.yaml --snapshot snapshot.yaml
```

### Rollback

Restore from backup:

```bash
sudo lltune rollback --backup /var/lib/lltune/backups/backup-<timestamp>/
```

### Safety Flags

Dangerous operations require explicit opt-in:

```yaml
safety:
  allow_grub_edit: true              # Required for kernel cmdline
  allow_dangerous_mitigations: true  # Required for mitigations=off
```

---

## Troubleshooting

### Common Issues

#### Permission Denied

```
Error: Permission denied
```

**Solution:** Run with sudo:
```bash
sudo lltune apply -c config.yaml
```

#### Module Not Found

```
ModuleNotFoundError: No module named 'lltune'
```

**Solution:** Set PYTHONPATH:
```bash
sudo PYTHONPATH=src lltune apply -c config.yaml
```

#### Config Validation Errors

```
Validation error: Invalid field 'xyz'
```

**Solution:** Check field names match schema. Run audit:
```bash
lltune audit -c config.yaml
```

#### NIC Not Found

```
Warning: NIC 'eth0' not found on system
```

**Solution:** Verify NIC names match `ip link` output.

### Verifying Tuning

After applying and rebooting, verify settings:

```bash
# CPU isolation
cat /sys/devices/system/cpu/isolated
# Expected: 1-27,57-83

# nohz_full
cat /sys/devices/system/cpu/nohz_full
# Expected: 1-27,57-83

# Hugepages
cat /proc/meminfo | grep -i huge
# Expected: HugePages_Total: 32768

# THP status
cat /sys/kernel/mm/transparent_hugepage/enabled
# Expected: always madvise [never]

# CPU governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
# Expected: performance

# Network sysctls
sysctl net.core.busy_poll net.core.busy_read
# Expected: 50, 50

# IRQ affinity (example for NIC)
cat /proc/irq/*/smp_affinity_list | head -10

# Kernel cmdline
cat /proc/cmdline
# Should contain: isolcpus=... nohz_full=... rcu_nocbs=...
```

### Log Files

```bash
# LLTune log
cat /var/log/lltune/lltune.log

# System journal for services
journalctl -u lltune-nic-restore
journalctl -u lltune-thp-setup
journalctl -u lltune-irq-affinity
journalctl -u lltune-workqueue
```

---

## References

### Official Documentation

- [RHEL 9 Real-Time Tuning Guide](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux_for_real_time/9/html/optimizing_rhel_9_for_real_time_for_low_latency_operation/index)
- [Red Hat CPU Isolation Article](https://access.redhat.com/articles/3720611)
- [RHEL Performance Guide](https://myllynen.github.io/rhel-performance-guide/index.html)

### Community Resources

- [Erik Rigtorp Low Latency Guide](https://rigtorp.se/low-latency-guide/)
- [Linux Kernel Network Documentation](https://docs.kernel.org/admin-guide/sysctl/net.html)

### Vendor Documentation

- [Solarflare Onload User Guide](https://www.amd.com/content/dam/amd/en/support/downloads/solarflare/onload/enterprise-onload/SF-104474-CD-34_Onload_User_Guide.pdf)
- [Mellanox VMA Documentation](https://github.com/Mellanox/libvma/wiki)

### Project Documentation

- [BIOS Tuning Guide](https://github.com/nawaz1991/lltune/blob/main/docs/BIOS_GUIDE.md) - Firmware/BIOS settings for low latency
- [Configuration Schema](https://github.com/nawaz1991/lltune/blob/main/docs/SCHEMA.md) - Complete config field reference
- [Operations Guide](https://github.com/nawaz1991/lltune/blob/main/docs/OPS_GUIDE.md) - Operational procedures
- [Rollback Guide](https://github.com/nawaz1991/lltune/blob/main/docs/ROLLBACK.md) - Backup and rollback procedures

---

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/nawaz1991/lltune/blob/main/LICENSE) file for details.

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For bug reports and feature requests, please open an issue on [GitHub](https://github.com/nawaz1991/lltune/issues).
