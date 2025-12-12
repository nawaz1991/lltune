"""Tests for validation hooks module."""

from lltune.validation_hooks import (
    LatencyStats,
    IrqRates,
    NicStats,
    ValidationResult,
    _parse_cpulist,
    compare_validation_results,
)


class TestDataclasses:
    """Tests for validation hook dataclasses."""

    def test_latency_stats_to_dict(self):
        stats = LatencyStats(
            min_us=1.0, avg_us=5.0, max_us=100.0, samples=1000
        )
        d = stats.to_dict()
        assert d["min_us"] == 1.0
        assert d["avg_us"] == 5.0
        assert d["max_us"] == 100.0
        assert d["samples"] == 1000

    def test_irq_rates_to_dict(self):
        rates = IrqRates(
            irq_rates={"eth0": 1000.0, "eth1": 500.0},
            duration_secs=5.0,
            total_interrupts=7500,
        )
        d = rates.to_dict()
        assert d["irq_rates"]["eth0"] == 1000.0
        assert d["duration_secs"] == 5.0

    def test_nic_stats_to_dict(self):
        stats = NicStats(
            interface="eth0",
            rx_packets=1000,
            tx_packets=500,
            rx_errors=0,
            tx_errors=0,
            rx_dropped=0,
            tx_dropped=0,
            duration_secs=5.0,
        )
        d = stats.to_dict()
        assert d["interface"] == "eth0"
        assert d["rx_packets"] == 1000

    def test_validation_result_to_dict(self):
        result = ValidationResult(
            timestamp="2025-01-01T00:00:00Z",
            phase="pre",
            latency=LatencyStats(min_us=1.0, avg_us=5.0, max_us=100.0),
            errors=["test error"],
        )
        d = result.to_dict()
        assert d["phase"] == "pre"
        assert d["latency"]["min_us"] == 1.0
        assert "test error" in d["errors"]


class TestParseCpulist:
    """Tests for CPU list parsing in validation_hooks module."""

    def test_single_cpu(self):
        assert _parse_cpulist("0") == [0]

    def test_range(self):
        assert _parse_cpulist("0-3") == [0, 1, 2, 3]

    def test_mixed(self):
        assert _parse_cpulist("0,2-4,8") == [0, 2, 3, 4, 8]

    def test_empty(self):
        assert _parse_cpulist("") == []


class TestCompareValidationResults:
    """Tests for comparing pre/post validation results."""

    def test_latency_improvement(self):
        pre = ValidationResult(
            timestamp="",
            phase="pre",
            latency=LatencyStats(min_us=1.0, avg_us=10.0, max_us=200.0),
        )
        post = ValidationResult(
            timestamp="",
            phase="post",
            latency=LatencyStats(min_us=1.0, avg_us=5.0, max_us=100.0),
        )
        summary = compare_validation_results(pre, post)
        assert "latency_max" in summary
        assert "Improved" in summary["latency_max"]

    def test_latency_degradation(self):
        pre = ValidationResult(
            timestamp="",
            phase="pre",
            latency=LatencyStats(min_us=1.0, avg_us=5.0, max_us=50.0),
        )
        post = ValidationResult(
            timestamp="",
            phase="post",
            latency=LatencyStats(min_us=1.0, avg_us=10.0, max_us=200.0),
        )
        summary = compare_validation_results(pre, post)
        assert "latency_max" in summary
        assert "Degraded" in summary["latency_max"]

    def test_irq_rate_change(self):
        pre = ValidationResult(
            timestamp="",
            phase="pre",
            irq_rates=IrqRates(
                irq_rates={}, duration_secs=5.0, total_interrupts=1000
            ),
        )
        post = ValidationResult(
            timestamp="",
            phase="post",
            irq_rates=IrqRates(
                irq_rates={}, duration_secs=5.0, total_interrupts=800
            ),
        )
        summary = compare_validation_results(pre, post)
        assert "irq_total" in summary

    def test_nic_drops_warning(self):
        pre = ValidationResult(
            timestamp="",
            phase="pre",
            nic_stats=[NicStats(interface="eth0", rx_dropped=0)],
        )
        post = ValidationResult(
            timestamp="",
            phase="post",
            nic_stats=[NicStats(interface="eth0", rx_dropped=10)],
        )
        summary = compare_validation_results(pre, post)
        assert "eth0_rx_dropped" in summary
        assert "Warning" in summary["eth0_rx_dropped"]
