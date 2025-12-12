"""Tests for IRQ affinity and CPU mask functions."""

import pytest

from lltune.utils import parse_cpulist, cpus_to_mask


class TestParseCpulist:
    """Tests for CPU list parsing."""

    def test_single_cpu(self):
        assert parse_cpulist("0") == [0]
        assert parse_cpulist("15") == [15]

    def test_comma_separated(self):
        assert parse_cpulist("0,1,2") == [0, 1, 2]
        assert parse_cpulist("0, 2, 4") == [0, 2, 4]

    def test_range(self):
        assert parse_cpulist("0-3") == [0, 1, 2, 3]
        assert parse_cpulist("8-11") == [8, 9, 10, 11]

    def test_mixed(self):
        # Note: parse_cpulist returns sorted, deduplicated list
        assert parse_cpulist("0,2-4,8") == [0, 2, 3, 4, 8]
        assert parse_cpulist("0-1,4-5,8-9") == [0, 1, 4, 5, 8, 9]

    def test_empty_string(self):
        assert parse_cpulist("") == []

    def test_invalid_values(self):
        # Should silently ignore invalid parts
        assert parse_cpulist("abc") == []
        assert parse_cpulist("0,abc,2") == [0, 2]

    def test_whitespace_handling(self):
        assert parse_cpulist(" 0 , 1 , 2 ") == [0, 1, 2]
        assert parse_cpulist("  0-3  ") == [0, 1, 2, 3]

    def test_invalid_range_raises(self):
        # Reversed ranges should raise ValueError
        with pytest.raises(ValueError):
            parse_cpulist("10-5")

    def test_negative_cpu_raises(self):
        # Negative CPU IDs should raise ValueError
        with pytest.raises(ValueError):
            parse_cpulist("-1")


class TestCpusToMask:
    """Tests for CPU list to hex mask conversion."""

    def test_single_cpu(self):
        assert cpus_to_mask([0]) == "1"
        assert cpus_to_mask([1]) == "2"
        assert cpus_to_mask([2]) == "4"
        assert cpus_to_mask([3]) == "8"

    def test_multiple_cpus(self):
        assert cpus_to_mask([0, 1]) == "3"
        assert cpus_to_mask([0, 1, 2, 3]) == "f"
        assert cpus_to_mask([0, 2, 4, 6]) == "55"

    def test_high_cpus(self):
        assert cpus_to_mask([8]) == "100"
        assert cpus_to_mask([8, 9, 10, 11]) == "f00"

    def test_empty_list(self):
        assert cpus_to_mask([]) == "0"

    def test_negative_cpu_ignored(self):
        # Negative CPUs should not set bits
        assert cpus_to_mask([-1]) == "0"


class TestMaskToCpus:
    """Tests for hex mask to CPU list conversion (from recommendations module)."""

    def test_single_cpu(self):
        from lltune.recommendations import _mask_to_cpus

        assert _mask_to_cpus("1") == [0]
        assert _mask_to_cpus("2") == [1]
        assert _mask_to_cpus("4") == [2]

    def test_multiple_cpus(self):
        from lltune.recommendations import _mask_to_cpus

        assert sorted(_mask_to_cpus("f")) == [0, 1, 2, 3]
        assert sorted(_mask_to_cpus("ff")) == list(range(8))

    def test_comma_separated_chunks(self):
        from lltune.recommendations import _mask_to_cpus

        # For systems with >32 CPUs, masks are comma-separated
        # The format is high,low (most significant first)
        # "ff,00000000" = CPUs 32-39 (not 0-7)
        # "00000000,ff" = CPUs 0-7
        assert sorted(_mask_to_cpus("00000000,ff")) == list(range(8))
        # Simple case without comma
        assert sorted(_mask_to_cpus("ff")) == list(range(8))

    def test_empty_mask(self):
        from lltune.recommendations import _mask_to_cpus

        assert _mask_to_cpus("") == []
        assert _mask_to_cpus("0") == []
