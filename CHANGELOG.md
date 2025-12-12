# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2025-12-12

### Fixed
- Fixed broken documentation links in PyPI README (converted to absolute GitHub URLs)

## [0.1.0] - 2025-12-12

### Added
- Initial release of lltune
- **Commands**: `scan`, `gen-config`, `audit`, `apply`, `rollback`
- **CPU tuning**: governor, core isolation, turbo boost, C-states, EPP
- **Memory**: hugepages (2MB/1GB), THP control, swap disable, mlock limits
- **Network**: sysctl optimization, NIC offloads, coalescing, ring buffers
- **Kernel**: boot parameter management via GRUB (isolcpus, nohz_full, rcu_nocbs)
- **IRQ**: affinity control, RPS/RFS disable, pattern-based matching
- **Time sync**: PTP/NTP configuration support
- **User-space stacks**: Onload, VMA, RDMA configuration generation
- **Safety features**: automatic backups, dry-run mode, rollback capability
- **Boot persistence**: systemd services for NIC, THP, and IRQ restoration
- Smart recommendations engine based on system discovery
- YAML configuration with schema validation
- Comprehensive CLI with text/JSON/YAML output formats
