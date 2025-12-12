"""Tests for persistence script generation."""

from lltune.persistence import (
    _render_nic_script,
    _render_thp_script,
    _render_irq_script,
)


class TestNicScriptGeneration:
    """Tests for NIC restore script generation."""

    def test_empty_config(self):
        cfg = {}
        snapshot = {"nics": []}
        script = _render_nic_script(cfg, snapshot)
        assert "#!/bin/bash" in script
        assert "set -euo pipefail" in script

    def test_offloads_disabled(self):
        cfg = {
            "network": {
                "defaults": {
                    "disable_gro": True,
                    "disable_lro": True,
                },
                "interfaces": [{"name": "eth0"}],
            }
        }
        snapshot = {"nics": [{"name": "eth0"}]}
        script = _render_nic_script(cfg, snapshot)
        assert "gro off" in script
        assert "lro off" in script
        assert "apply_eth0" in script

    def test_coalescing_settings(self):
        cfg = {
            "network": {
                "interfaces": [
                    {
                        "name": "eth0",
                        "coalescing": {"rx_usecs": 0, "tx_usecs": 0},
                    }
                ],
            }
        }
        snapshot = {}
        script = _render_nic_script(cfg, snapshot)
        assert "ethtool -C" in script or "$ETHTOOL_BIN -C" in script
        assert "rx-usecs 0" in script
        assert "tx-usecs 0" in script

    def test_ring_sizes(self):
        cfg = {
            "network": {
                "interfaces": [
                    {
                        "name": "eth0",
                        "rings": {"rx": 4096, "tx": 4096},
                    }
                ],
            }
        }
        snapshot = {}
        script = _render_nic_script(cfg, snapshot)
        assert "-G" in script
        assert "rx 4096" in script
        assert "tx 4096" in script

    def test_flow_control(self):
        cfg = {
            "network": {
                "interfaces": [
                    {
                        "name": "eth0",
                        "flow_control": {"rx": False, "tx": False},
                    }
                ],
            }
        }
        snapshot = {}
        script = _render_nic_script(cfg, snapshot)
        assert "-A" in script
        assert "rx off" in script
        assert "tx off" in script

    def test_interface_sanitization(self):
        # Interface names with dots/dashes should be sanitized for function
        # names
        cfg = {
            "network": {
                "interfaces": [{"name": "eth0.100"}],
            }
        }
        snapshot = {}
        script = _render_nic_script(cfg, snapshot)
        assert "apply_eth0_100" in script  # dots replaced with underscores


class TestThpScriptGeneration:
    """Tests for THP/hugepage script generation."""

    def test_thp_never(self):
        memory_cfg = {"thp_runtime": "never"}
        script = _render_thp_script(memory_cfg)
        assert 'mode="never"' in script
        assert "$thp_base/enabled" in script

    def test_hugepages_total(self):
        memory_cfg = {"hugepages": {"size_kb": "2048", "total": 4096}}
        script = _render_thp_script(memory_cfg)
        assert "hugepages-2048kB" in script
        assert '"4096"' in script

    def test_hugepages_per_node(self):
        memory_cfg = {
            "hugepages": {
                "size_kb": "2048",
                "per_node": {"node0": 1024, "node1": 1024},
            }
        }
        script = _render_thp_script(memory_cfg)
        assert "node0)" in script
        assert "node1)" in script
        assert '"1024"' in script


class TestIrqScriptGeneration:
    """Tests for IRQ affinity script generation."""

    def test_no_rules(self):
        cfg = {"irq": {}}
        script = _render_irq_script(cfg)
        assert "No IRQ affinity rules configured" in script

    def test_manual_affinity_rules(self):
        cfg = {
            "irq": {
                "manual_affinity": [
                    {"match": "eth0-TxRx-*", "cpus": [0, 1]},
                    {"match": "eth1-*", "cpus": "8-9"},
                ]
            }
        }
        script = _render_irq_script(cfg)
        assert "apply_irq_affinity" in script
        assert "eth0-TxRx-*" in script
        assert "0,1" in script

    def test_cpulist_to_mask_function(self):
        cfg = {"irq": {"manual_affinity": [{"match": "test", "cpus": [0]}]}}
        script = _render_irq_script(cfg)
        assert "smp_affinity_list" in script
        assert 'echo "$cpulist" > "/proc/irq/${irq_num}/smp_affinity_list"' in script
