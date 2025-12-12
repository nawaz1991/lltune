# LLTune Configuration Schema Reference

This document provides a complete reference for the LLTune configuration YAML schema.

## Schema Version

Current schema version: **1**

The configuration must include a `version` field at the root level:

```yaml
version: 1
```

Schema versioning follows semantic principles:
- Breaking changes increment the major version
- New optional fields do not change the version
- Deprecated fields remain supported for one major version

---

## Top-Level Structure

```yaml
version: 1                    # Required: Schema version (integer)
metadata: {}                  # Auto-generated: Tool and host info
hardware: {}                  # Read-only: Hardware snapshot
cpu: {}                       # CPU tuning configuration
kernel: {}                    # Kernel command line configuration
memory: {}                    # Memory and hugepage configuration
network: {}                   # NIC tuning configuration
irq: {}                       # IRQ affinity configuration
time_sync: {}                 # Time synchronization configuration
services: {}                  # System services configuration
safety: {}                    # Safety guardrails
onload: {}                    # Optional: Solarflare Onload settings
vma: {}                       # Optional: Mellanox VMA settings
rdma: {}                      # Optional: RDMA device settings
recommendations: []           # Auto-generated: Tuning recommendations
```

---

## Section Reference

### `version` (Required)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | integer | Yes | Schema version, must be `1` |

### `metadata` (Auto-generated)

Generated automatically during config creation. Read-only.

| Field | Type | Description |
|-------|------|-------------|
| `generated_at` | string | ISO 8601 timestamp |
| `host` | string | Hostname |
| `kernel` | string | Kernel version |
| `tool_version` | string | LLTune version |

### `hardware` (Read-only)

Hardware information captured from system discovery. Read-only reference.

| Field | Type | Description |
|-------|------|-------------|
| `sockets` | integer | Number of CPU sockets |
| `cores_per_socket` | integer | Physical cores per socket |
| `threads_per_core` | integer | Threads per core (SMT) |
| `numa_nodes` | integer | Number of NUMA nodes |
| `nics` | array | List of NIC names |

---

### `cpu`

CPU frequency, governor, and power management settings.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `governor.target` | string | - | CPU frequency governor |
| `isolate_cores` | string | - | CPUs to isolate (e.g., "2-7,10-15") |
| `turbo` | boolean | - | Enable/disable turbo boost |
| `cstate_limit` | integer | - | Maximum C-state (0-5) |
| `cstate_disable_deeper_than` | integer | - | Disable C-states deeper than N |
| `epp` | string | - | Energy Performance Preference |
| `uncore_min_freq_khz` | integer | - | Minimum uncore frequency |

#### `cpu.governor.target` Valid Values

| Value | Description |
|-------|-------------|
| `performance` | Fixed maximum frequency (recommended for HFT) |
| `powersave` | Fixed minimum frequency |
| `schedutil` | Scheduler-driven (kernel 4.7+) |
| `ondemand` | Dynamic frequency scaling |
| `conservative` | Gradual frequency scaling |
| `userspace` | User-controlled frequency |

#### `cpu.epp` Valid Values

| Value | Description |
|-------|-------------|
| `performance` | Maximum performance, highest power |
| `balance_performance` | Favor performance |
| `balance_power` | Favor power saving |
| `power` | Maximum power saving |

#### Example

```yaml
cpu:
  governor:
    target: performance
  isolate_cores: "2-7,10-15"
  turbo: false
  cstate_limit: 1
  epp: performance
```

---

### `kernel`

Kernel command line (GRUB) configuration.

| Field | Type | Description |
|-------|------|-------------|
| `cmdline` | object | Key-value pairs for kernel parameters |

#### Common `cmdline` Keys

| Key | Example Value | Description |
|-----|---------------|-------------|
| `isolcpus` | `2-7,10-15` | CPUs excluded from scheduler |
| `nohz_full` | `2-7,10-15` | CPUs with disabled tick (adaptive-ticks) |
| `rcu_nocbs` | `2-7,10-15` | CPUs with offloaded RCU callbacks |
| `mitigations` | `off` | Disable CPU vulnerability mitigations |
| `transparent_hugepage` | `never` | Boot-time THP setting |
| `idle` | `poll` | CPU idle mode (poll = no sleep) |
| `intel_pstate` | `disable` | Disable Intel P-state driver |
| `processor.max_cstate` | `1` | ACPI C-state limit |
| `intel_idle.max_cstate` | `0` | Intel idle C-state limit |
| `clocksource` | `tsc` | Force clocksource |
| `tsc` | `reliable` | Mark TSC as reliable |

#### Example

```yaml
kernel:
  cmdline:
    isolcpus: "2-7,10-15"
    nohz_full: "2-7,10-15"
    rcu_nocbs: "2-7,10-15"
    mitigations: "off"
    transparent_hugepage: "never"
```

**Important**: Requires `safety.allow_grub_edit: true` to apply.

---

### `memory`

Memory management and hugepage configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `thp_runtime` | string | - | THP mode at runtime |
| `swap_disable` | boolean | - | Disable swap devices |
| `numa_balancing` | boolean | - | NUMA automatic balancing |
| `ksm` | boolean | - | Kernel Same-page Merging |
| `hugepages.size_kb` | string | `2048` | Hugepage size in KB |
| `hugepages.total` | integer | - | Total hugepages to allocate |
| `hugepages.per_node` | object | - | Per-NUMA-node allocation |

#### `memory.thp_runtime` Valid Values

| Value | Description |
|-------|-------------|
| `never` | THP disabled (recommended for HFT) |
| `always` | THP always enabled |
| `madvise` | THP enabled via madvise() |

#### Example

```yaml
memory:
  thp_runtime: never
  swap_disable: true
  numa_balancing: false
  ksm: false
  hugepages:
    size_kb: "2048"
    total: 4096
    per_node:
      node0: 2048
      node1: 2048
```

---

### `network`

NIC tuning configuration.

| Field | Type | Description |
|-------|------|-------------|
| `defaults` | object | Default settings for all NICs |
| `interfaces` | array | Per-interface configuration |

#### `network.defaults`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `disable_gro` | boolean | `true` | Disable Generic Receive Offload |
| `disable_lro` | boolean | `true` | Disable Large Receive Offload |
| `disable_tso` | boolean | `true` | Disable TCP Segmentation Offload |
| `disable_gso` | boolean | `true` | Disable Generic Segmentation Offload |

#### `network.interfaces[]`

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Interface name (e.g., "eth0") |
| `role` | string | Role: "trading", "control", "multicast" |
| `coalescing` | object | Interrupt coalescing settings |
| `rings` | object | Ring buffer sizes |
| `flow_control` | object | Flow control settings |
| `queues` | object | Queue configuration |

##### `coalescing` Fields

| Field | Type | Description |
|-------|------|-------------|
| `rx_usecs` | integer | RX interrupt delay (microseconds) |
| `tx_usecs` | integer | TX interrupt delay (microseconds) |
| `rx_frames` | integer | RX frames before interrupt |
| `tx_frames` | integer | TX frames before interrupt |

##### `rings` Fields

| Field | Type | Description |
|-------|------|-------------|
| `rx` | integer | RX ring buffer size |
| `tx` | integer | TX ring buffer size |

##### `flow_control` Fields

| Field | Type | Description |
|-------|------|-------------|
| `rx` | boolean | Enable RX flow control |
| `tx` | boolean | Enable TX flow control |

##### `queues` Fields

| Field | Type | Description |
|-------|------|-------------|
| `combined` | integer | Combined RX/TX queues |
| `rx` | integer | RX-only queues |
| `tx` | integer | TX-only queues |

#### Example

```yaml
network:
  defaults:
    disable_gro: true
    disable_lro: true
    disable_tso: true
    disable_gso: true
  interfaces:
    - name: eth0
      role: trading
      coalescing:
        rx_usecs: 0
        tx_usecs: 0
      rings:
        rx: 4096
        tx: 4096
      flow_control:
        rx: false
        tx: false
    - name: eth1
      role: control
```

---

### `irq`

IRQ affinity configuration.

| Field | Type | Description |
|-------|------|-------------|
| `manual_affinity` | array | IRQ pinning rules |
| `avoid_cores_for_irqs` | string | CPUs to avoid for IRQs |
| `disable_rps` | boolean | Disable Receive Packet Steering |
| `disable_rfs` | boolean | Disable Receive Flow Steering |

#### `manual_affinity[]`

| Field | Type | Description |
|-------|------|-------------|
| `match` | string | IRQ description pattern (glob) |
| `cpus` | array/string | CPU IDs or range to pin |

#### Example

```yaml
irq:
  manual_affinity:
    - match: "eth0-TxRx-*"
      cpus: [0, 1]
    - match: "eth1-*"
      cpus: "8-9"
  avoid_cores_for_irqs: "2-7,10-15"
  disable_rps: true
  disable_rfs: true
```

---

### `time_sync`

Time synchronization configuration.

| Field | Type | Description |
|-------|------|-------------|
| `ntp` | boolean | Enable NTP synchronization |
| `ptp.interface` | string | PTP interface |
| `ptp.phc2sys` | boolean | Enable PHC to system clock sync |
| `ptp.domain` | integer | PTP domain number |
| `ptp.priority1` | integer | PTP clock priority |
| `ptp.transport` | string | PTP transport: "L2" or "UDPv4" |

#### Example

```yaml
time_sync:
  ntp: true
  ptp:
    interface: eth0
    phc2sys: true
    domain: 0
    priority1: 128
    transport: L2
```

---

### `services`

System services configuration.

| Field | Type | Description |
|-------|------|-------------|
| `irqbalance` | boolean | Enable/disable irqbalance |
| `tuned` | string/null | tuned profile name or null |

#### Example

```yaml
services:
  irqbalance: false
  tuned: latency-performance
```

---

### `safety`

Safety guardrails to prevent accidental damage.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `allow_grub_edit` | boolean | `false` | Allow kernel cmdline modification |
| `allow_dangerous_mitigations` | boolean | `false` | Allow disabling CPU mitigations |

#### Example

```yaml
safety:
  allow_grub_edit: true
  allow_dangerous_mitigations: false
```

---

### `onload` (Optional)

Solarflare Onload stack configuration.

| Field | Type | Description |
|-------|------|-------------|
| `generate_profile` | boolean | Generate environment profile |
| `tuning_level` | string | "ultra_low_latency", "low_latency", "balanced" |

### `vma` (Optional)

Mellanox VMA stack configuration.

| Field | Type | Description |
|-------|------|-------------|
| `generate_profile` | boolean | Generate environment profile |
| `tuning_level` | string | "ultra_low_latency", "low_latency", "balanced" |

### `rdma` (Optional)

RDMA device configuration.

| Field | Type | Description |
|-------|------|-------------|
| `devices` | array | RDMA device names to configure |

---

## Validation Rules

### Cross-Field Validation

1. **isolcpus/nohz_full/rcu_nocbs consistency**: These should specify the same CPU sets
2. **CPU ID bounds**: All CPU IDs must exist on the system
3. **NIC existence**: All interface names must exist
4. **NUMA node existence**: All NUMA nodes in `per_node` must exist
5. **Hugepage memory**: Total hugepage allocation cannot exceed available memory
6. **Governor enum**: Must be a valid governor name

### Safety Validation

1. Kernel cmdline changes are applied only when `allow_grub_edit: true` (otherwise they are skipped)
2. When `allow_grub_edit: true`, kernel cmdline values must not contain `TODO` placeholders
3. `mitigations=off` requires `allow_dangerous_mitigations: true`
4. Dangerous kernel flags (noapic, nolapic, nosmp) are blocked

---

## Example Complete Configuration

```yaml
version: 1

cpu:
  governor:
    target: performance
  isolate_cores: "2-15"
  turbo: false
  cstate_limit: 1
  epp: performance

kernel:
  cmdline:
    isolcpus: "2-15"
    nohz_full: "2-15"
    rcu_nocbs: "2-15"
    mitigations: "off"
    transparent_hugepage: "never"
    idle: "poll"

memory:
  thp_runtime: never
  swap_disable: true
  numa_balancing: false
  ksm: false
  hugepages:
    size_kb: "2048"
    total: 8192
    per_node:
      node0: 4096
      node1: 4096

network:
  defaults:
    disable_gro: true
    disable_lro: true
    disable_tso: true
    disable_gso: true
  interfaces:
    - name: eth0
      role: trading
      coalescing:
        rx_usecs: 0
        tx_usecs: 0
      rings:
        rx: 4096
        tx: 4096

irq:
  manual_affinity:
    - match: "eth0-TxRx-*"
      cpus: [0, 1]
  avoid_cores_for_irqs: "2-15"
  disable_rps: true
  disable_rfs: true

time_sync:
  ntp: true
  ptp:
    interface: eth0
    phc2sys: true

services:
  irqbalance: false
  tuned: latency-performance

safety:
  allow_grub_edit: true
  allow_dangerous_mitigations: true
```

---

## Error Messages Reference

| Error | Cause | Solution |
|-------|-------|----------|
| `Unknown top-level key` | Unrecognized config section | Remove or rename the key |
| `Missing config version` | No `version` field | Add `version: 1` |
| `Incompatible config version` | Version mismatch | Update config to current schema |
| `Kernel cmdline contains TODO placeholders` | `safety.allow_grub_edit=true` with `TODO` values under `kernel.cmdline` | Replace TODOs (or disable GRUB edits) |
| `mitigations=off requires safety.allow_dangerous_mitigations=true` | Attempting to disable CPU mitigations without explicit opt-in | Set `allow_dangerous_mitigations: true` (or use `mitigations: auto`) |
| `Invalid CPU IDs` | CPU doesn't exist | Check available CPUs with `lscpu` |
| `NIC not found` | Interface doesn't exist | Run `ip link` to see available NICs |
| `NUMA node does not exist` | Invalid NUMA node | Check with `numactl -H` |
| `Hugepages exceed available memory` | Over-allocation | Reduce total hugepages |
| `Invalid governor` | Unknown governor name | Use valid governor enum |
