"""Tests for user stack configuration generation."""

from lltune.user_stack_config import (
    generate_onload_profile,
    generate_vma_profile,
    validate_rdma_alignment,
)


class TestOnloadProfileGeneration:
    """Tests for Onload environment profile generation."""

    def test_basic_profile(self):
        profile = generate_onload_profile()
        assert "#!/bin/bash" in profile
        assert "EF_" in profile  # Onload env vars

    def test_ultra_low_latency(self):
        profile = generate_onload_profile(tuning_level="ultra_low_latency")
        assert 'EF_SPIN_USEC="-1"' in profile  # Infinite spin
        assert 'EF_INT_DRIVEN="0"' in profile  # No interrupts

    def test_low_latency(self):
        profile = generate_onload_profile(tuning_level="low_latency")
        # Should have some polling, but with limits
        assert "EF_POLL_USEC" in profile

    def test_balanced(self):
        profile = generate_onload_profile(tuning_level="balanced")
        assert 'EF_INT_DRIVEN="1"' in profile  # Use interrupts

    def test_multicast_role(self):
        profile = generate_onload_profile(nic_role="multicast")
        assert "EF_MCAST" in profile

    def test_interface_binding(self):
        profile = generate_onload_profile(interface="eth0")
        assert 'EF_INTERFACE="eth0"' in profile


class TestVmaProfileGeneration:
    """Tests for VMA environment profile generation."""

    def test_basic_profile(self):
        profile = generate_vma_profile()
        assert "#!/bin/bash" in profile
        assert "VMA_" in profile  # VMA env vars

    def test_ultra_low_latency(self):
        profile = generate_vma_profile(tuning_level="ultra_low_latency")
        assert 'VMA_RX_POLL="-1"' in profile  # Infinite poll
        assert 'VMA_CQ_MODERATION_ENABLE="0"' in profile

    def test_balanced(self):
        profile = generate_vma_profile(tuning_level="balanced")
        assert 'VMA_RX_POLL="0"' in profile  # Interrupt-driven

    def test_interface_binding(self):
        profile = generate_vma_profile(interface="eth0")
        assert 'VMA_INTF="eth0"' in profile

    def test_run_with_vma_function(self):
        profile = generate_vma_profile()
        assert "run_with_vma()" in profile
        assert "LD_PRELOAD" in profile


class TestRdmaAlignmentValidation:
    """Tests for RDMA/NIC NUMA alignment validation."""

    def test_aligned_devices(self):
        rdma_devices = [{"name": "mlx5_0", "numa_node": 0}]
        nics = [{"name": "eth0", "numa_node": 0}]
        issues = validate_rdma_alignment(rdma_devices, nics)
        # No issues for aligned devices
        cross_numa_issues = [i for i in issues if "cross-NUMA" in i.message]
        assert len(cross_numa_issues) == 0

    def test_no_rdma_devices(self):
        issues = validate_rdma_alignment([], [])
        assert len(issues) == 0

    def test_missing_numa_info(self):
        rdma_devices = [{"name": "mlx5_0", "numa_node": None}]
        nics = []
        issues = validate_rdma_alignment(rdma_devices, nics)
        # Should warn about missing NUMA info
        info_issues = [i for i in issues if i.severity == "info"]
        assert len(info_issues) > 0
