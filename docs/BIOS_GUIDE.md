# BIOS/Firmware Tuning Guide for HFT Servers

This guide covers BIOS/UEFI settings for low-latency trading servers. These settings complement the OS-level tuning performed by lltune.

**Important**: BIOS settings vary by vendor and motherboard model. The exact menu names and options may differ. Always document your current settings before making changes.

## Quick Reference

| Setting | Recommended Value | Impact |
|---------|------------------|--------|
| C-States | C1 only or disabled | High |
| C6/Deep C-States | Disabled | High |
| P-States | OS control or disabled | Medium |
| Turbo Boost | Depends on workload | Medium |
| Hyper-Threading | Disabled or careful isolation | Medium |
| NUMA Interleaving | Disabled | High |
| Power Management | Maximum Performance | High |
| Memory Frequency | Maximum rated | Medium |

---

## 1. C-State Configuration (Critical)

C-states are CPU idle power states. Higher C-states (C3, C6, C10) save power but introduce significant wake-up latency.

### Settings

| C-State | Wake Latency | Recommendation |
|---------|-------------|----------------|
| C0 | 0 | Active state |
| C1/C1E | 1-10 μs | Safe to enable |
| C3 | 50-100 μs | Disable |
| C6 | 100-200 μs | **Must disable** |
| C7/C10 | 200+ μs | **Must disable** |

### Intel Xeon BIOS Settings

```
Advanced > Processor Configuration > C-States:
  - Package C-State Limit: C1 (or C0/C1 auto)
  - C1E: Enabled (adds ~2μs but saves power when truly idle)
  - C3/C6 Report: Disabled
  - C6 Enable: Disabled
  - Enhanced Halt State (C1E): Enabled

Advanced > Power & Performance:
  - CPU C-State Control: Enabled
  - Package C-State: C1 (or Processor C1 state)
```

### AMD EPYC BIOS Settings

```
Advanced > AMD CBS > CPU Common Options:
  - Global C-State Control: C1 Only (or Disabled)
  - Power Supply Idle Control: Typical Current Idle (or disabled)
  - DF C-States: Disabled

Advanced > AMD CBS > NBIO Common Options:
  - SMU Common Options > Determinism Control: Manual
  - SMU Common Options > Determinism Slider: Power
```

### Kernel Command Line (Fallback)

If BIOS options are limited, use kernel parameters:

```bash
# Limit to C1 only
intel_idle.max_cstate=1 processor.max_cstate=1

# Disable completely (use idle=poll for isolated cores)
idle=poll  # WARNING: 100% CPU usage
```

---

## 2. P-State Configuration

P-states control CPU frequency scaling. For consistent latency, either lock to maximum frequency or use OS control with the performance governor.

### Intel Xeon Settings

```
Advanced > Processor Configuration:
  - Intel SpeedStep (EIST): Disabled (for fixed max frequency)
    OR
  - Intel SpeedStep (EIST): Enabled (let OS control with performance governor)

  - Intel Speed Shift Technology: Disabled (for predictability)
  - Turbo Mode: See Turbo section

Advanced > Power & Performance:
  - Hardware P-States: Disabled or Native Mode
  - EPB (Energy Performance Bias): Performance
```

### AMD EPYC Settings

```
Advanced > AMD CBS > NBIO Common Options:
  - SMU Common Options > CPPC: Disabled (for fixed frequency)
    OR
  - SMU Common Options > CPPC: Enabled (let OS control)
  - SMU Common Options > CPPC Preferred Cores: Disabled
```

### OS-Level Control

When using OS control:

```bash
# Set governor to performance on all CPUs
for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > $cpu
done

# Verify
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

---

## 3. Turbo Boost / Precision Boost

Turbo allows CPUs to exceed base frequency when thermal/power headroom exists.

### Trade-offs

| Mode | Pros | Cons |
|------|------|------|
| Enabled | Higher peak frequency | Frequency varies, cross-core effects |
| Disabled | Consistent frequency | Lower peak performance |

### Recommendation

For **ultra-low-latency** (determinism critical):
- **Disable Turbo Boost** to eliminate frequency variation

For **latency-sensitive but throughput important**:
- **Enable Turbo** and accept slight jitter for better average performance

### Intel Settings

```
Advanced > Processor Configuration:
  - Intel Turbo Boost Technology: Disabled/Enabled
  - Turbo Boost Max Technology 3.0: Disabled (reduces core-to-core variance)
```

### AMD Settings

```
Advanced > AMD CBS > CPU Common Options:
  - Core Performance Boost: Disabled/Enabled
  - Precision Boost Overdrive: Disabled (for consistency)
```

---

## 4. Hyper-Threading / SMT

Hyper-Threading (Intel) or SMT (AMD) shares physical core resources between two logical threads.

### Impact on Latency

- Cache pollution from sibling thread
- Execution port contention
- Unpredictable latency spikes

### Recommendations

**Option 1: Disable SMT entirely** (most predictable)
```
Advanced > Processor Configuration:
  - Hyper-Threading: Disabled (Intel)
  - SMT Control: Disabled (AMD)
```

**Option 2: Keep enabled, isolate carefully**
- Isolate both threads of a physical core for trading
- Never schedule OS tasks on sibling of trading thread

```bash
# Check thread topology
lscpu -e

# Isolate both threads of physical core 1 (threads 1 and 21 on 40-core 2-socket)
# Add to kernel cmdline: isolcpus=1,21 nohz_full=1,21 rcu_nocbs=1,21
```

---

## 5. NUMA Configuration

For multi-socket systems, NUMA settings are critical.

### NUMA Interleaving

```
Advanced > Memory Configuration:
  - NUMA Optimized: Enabled
  - Memory Interleaving: Disabled (per-socket local access)

Advanced > UPI/QPI Configuration:
  - SNC (Sub-NUMA Clustering): Disabled or SNC-2
```

**Why disable interleaving?**
- With interleaving, memory is striped across nodes
- Local access becomes impossible
- Latency increases by ~30-50ns

### Memory Proximity

- Pin trading applications to specific NUMA node
- Ensure NIC is on same NUMA node as application
- Use `numactl --membind=<node>` for memory allocation

---

## 6. Power Management Profile

Set the overall power profile to performance mode.

### Intel Settings

```
Advanced > Power & Performance:
  - Power Technology: Custom or Performance
  - Energy Efficient Turbo: Disabled
  - Energy Performance BIAS: Performance or Max Performance
  - ENERGY_PERF_BIAS_CFG mode: Performance

Advanced > Processor Configuration:
  - Power Performance Tuning: OS Controls EPB
  - Energy Performance BIAS setting: Performance
```

### AMD Settings

```
Advanced > AMD CBS > NBIO Common Options:
  - Power Profile Selection: High Performance

Advanced > AMD CBS > CPU Common Options:
  - Power Supply Idle Control: Typical Current Idle
```

---

## 7. Memory Configuration

### Frequency

Always run memory at its rated speed:

```
Advanced > Memory Configuration:
  - Memory Frequency: Max Performance or specific DDR4-3200/DDR5-4800
  - Memory Operating Speed: Auto or Rated Speed
```

### Memory Patrol Scrub

Memory scrubbing corrects errors but can cause latency spikes:

```
Advanced > Memory Configuration:
  - Patrol Scrub: Disabled during trading hours
    OR
  - Patrol Scrub: Low Rate (if required)
```

### Channel Interleaving

```
Advanced > Memory Configuration:
  - Channel Interleaving: Auto (maximize bandwidth)
  - Rank Interleaving: Auto
```

---

## 8. Other Important Settings

### Secure Boot / TPM

```
Security > Secure Boot:
  - Secure Boot: Disabled (may interfere with custom kernels)
  - TPM: As required by security policy
```

### Virtualization

If not using VMs:

```
Advanced > Processor Configuration:
  - Intel VT-x: Disabled
  - Intel VT-d: Disabled
  - AMD-V/SVM: Disabled
  - IOMMU: Disabled
```

### Serial Console / BMC

```
Server Management:
  - SOL (Serial Over LAN): Disabled (reduces IRQ noise)
  - Console Redirection: Disabled after initial setup
```

### USB/Legacy Devices

```
Advanced > USB Configuration:
  - Legacy USB Support: Disabled
  - XHCI Hand-off: Enabled

Advanced > Boot:
  - CSM (Compatibility Support Module): Disabled
```

---

## 9. BIOS Update Considerations

- **Test updates in non-production first**
- BIOS updates can reset settings to defaults
- Document all settings before updating
- Some updates include microcode with latency implications
- Intel microcode may add speculative execution mitigations

---

## 10. Verification After Changes

### Check C-State Configuration

```bash
# View available and current C-states
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/name
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/latency

# Check if deep C-states are used
turbostat --show Pkg%pc6,Pkg%pc3,Core%c6,Core%c3 --interval 5
```

### Check Frequency

```bash
# View current frequency
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq

# Watch frequency changes
watch -n1 'grep MHz /proc/cpuinfo | head -10'

# Use turbostat for detailed view
turbostat --show Core,CPU,Avg_MHz,Busy%,Bzy_MHz --interval 1
```

### Check NUMA

```bash
# View NUMA topology
numactl --hardware
lscpu | grep NUMA

# Check NIC NUMA placement
cat /sys/class/net/eth0/device/numa_node
```

### Check Turbo Status

```bash
# Intel
cat /sys/devices/system/cpu/intel_pstate/no_turbo  # 0=enabled, 1=disabled

# AMD
cat /sys/devices/system/cpu/cpufreq/boost
```

---

## 11. Vendor-Specific Quick Guides

### Dell PowerEdge

```
System BIOS > System Profile Settings:
  - System Profile: Performance
  - CPU Power Management: Maximum Performance
  - Memory Frequency: Maximum Performance
  - Turbo Boost: Enabled/Disabled (per requirements)
  - C-States: C1 only
  - C1E: Enabled
  - Memory Patrol Scrub: Disabled
  - Memory Refresh Rate: 1x
  - Uncore Frequency: Maximum
  - Energy Efficient Policy: Performance
  - Monitor/Mwait: Enabled
```

### HPE ProLiant

```
System Configuration > BIOS/Platform Configuration:
  - Power Regulator: Static High Performance
  - Minimum Processor Idle Power Core C-State: C1E State
  - Processor C-State Support: Enabled (C1 only)
  - Intel Turbo Boost Technology: Per requirements
  - Energy/Performance Bias: Maximum Performance
  - NUMA Group Size Optimization: Flat
  - Sub-NUMA Clustering: Disabled
```

### Supermicro

```
Advanced > CPU Configuration:
  - Power Technology: Custom
  - Enhanced SpeedStep (EIST): Enabled
  - Turbo Mode: Per requirements
  - C-States: Enabled
  - Package C-State: C0/C1 state
  - C1E Support: Enabled
  - Intel Speed Shift: Disabled

Advanced > Power Configuration:
  - Power Performance Tuning: OS Controls EPB
  - ENERGY_PERF_BIAS_CFG: Performance
```

---

## 12. RHEL 9 / AlmaLinux 9 Specific Recommendations

This section covers tuning specific to RHEL 9 and compatible distributions (AlmaLinux 9, Rocky Linux 9, CentOS Stream 9).

### TuneD Profiles

RHEL 9 provides specialized tuned profiles for real-time workloads:

```bash
# Install real-time tuned profiles
dnf install tuned-profiles-realtime

# Apply latency-performance profile
tuned-adm profile latency-performance

# Or for real-time kernel
tuned-adm profile realtime
```

### Recommended Kernel Parameters for RHEL 9

Based on [RHEL 9 Real-Time documentation](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux_for_real_time/9/html/optimizing_rhel_9_for_real_time_for_low_latency_operation/index):

```bash
# Example for 96-core machine, isolating cores 1-95
GRUB_CMDLINE_LINUX="console=tty0 skew_tick=1 tsc=reliable \
  rcupdate.rcu_normal_after_boot=1 \
  isolcpus=managed_irq,domain,1-95 \
  nohz=on nohz_full=1-95 \
  rcu_nocbs=1-95 \
  kthread_cpus=0 irqaffinity=0 \
  intel_pstate=disable \
  nosoftlockup nmi_watchdog=0 \
  transparent_hugepage=never"
```

**Parameter explanations:**

| Parameter | Purpose |
|-----------|---------|
| `skew_tick=1` | Reduces jitter from timer tick alignment |
| `tsc=reliable` | Marks TSC as reliable for timekeeping |
| `isolcpus=managed_irq,domain,1-95` | Isolates CPUs with managed IRQ support |
| `nohz_full=1-95` | Enables adaptive-tick (tickless) on isolated CPUs |
| `rcu_nocbs=1-95` | Offloads RCU callbacks from isolated CPUs |
| `kthread_cpus=0` | Pins kernel threads to CPU 0 |
| `irqaffinity=0` | Default IRQ affinity to CPU 0 |
| `intel_pstate=disable` | Allows acpi-cpufreq for better control |
| `nosoftlockup` | Disables soft lockup detector |
| `nmi_watchdog=0` | Disables NMI watchdog |

### Workqueue Isolation

Move kernel workqueues off isolated CPUs:

```bash
# Move all workqueues to CPU 0
for wq in /sys/devices/virtual/workqueue/*/cpumask; do
  echo 1 > "$wq"
done

# Or use tuna utility
tuna --cpus=1-95 --isolate
```

### Verifying Isolation

```bash
# Check isolated CPUs
cat /sys/devices/system/cpu/isolated

# Check nohz_full CPUs
cat /sys/devices/system/cpu/nohz_full

# Check timer interrupts per CPU (should be near zero on isolated)
perf stat -e 'irq_vectors:local_timer_entry' -a -A --timeout 30000

# Check context switches
perf stat -e 'sched:sched_switch' -a -A --timeout 10000
```

### RHEL 9 Sysctl Defaults for Low Latency

```bash
# /etc/sysctl.d/99-lltune.conf
kernel.numa_balancing=0
vm.swappiness=0
vm.stat_interval=120
vm.dirty_ratio=10
vm.dirty_background_ratio=5
vm.max_map_count=262144

# Network tuning
net.core.busy_poll=50
net.core.busy_read=50
net.core.rmem_max=67108864
net.core.wmem_max=67108864
net.ipv4.tcp_timestamps=0
net.ipv4.tcp_sack=0
```

---

## 13. References

- [Red Hat Enterprise Linux for Real Time 9 - Optimizing for low latency](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux_for_real_time/9/html/optimizing_rhel_9_for_real_time_for_low_latency_operation/index)
- [Red Hat Article: isolcpus, nohz_full, rcu_nocbs usage](https://access.redhat.com/articles/3720611)
- [RHEL Performance Guide (GitHub)](https://myllynen.github.io/rhel-performance-guide/index.html)
- [Erik Rigtorp Low Latency Guide](https://rigtorp.se/low-latency-guide/)
- [Intel Xeon Scalable BIOS Guide](https://www.intel.com/content/www/us/en/developer/articles/technical/xeon-processor-scalable-family-technical-overview.html)
- [AMD EPYC Tuning Guides](https://www.amd.com/en/search/documentation/hub.html#q=tuning%20guide&f-amd_document_type=Tuning%20Guides)
- [Linux Kernel Documentation - CPU Idle](https://www.kernel.org/doc/html/latest/admin-guide/pm/cpuidle.html)
