"""Tests for kernel command line merging functionality."""

from lltune.apply_engine import _merge_cmdline


class TestMergeCmdline:
    """Tests for _merge_cmdline function."""

    def test_empty_existing(self):
        result = _merge_cmdline({}, {"isolcpus": "2-7"})
        assert "isolcpus=2-7" in result

    def test_empty_desired(self):
        result = _merge_cmdline({"quiet": ""}, {})
        assert "quiet" in result

    def test_merge_preserves_existing(self):
        existing = {"quiet": "", "rhgb": ""}
        desired = {"isolcpus": "2-7"}
        result = _merge_cmdline(existing, desired)
        assert "quiet" in result
        assert "rhgb" in result
        assert "isolcpus=2-7" in result

    def test_merge_overwrites_existing(self):
        existing = {"isolcpus": "0-1"}
        desired = {"isolcpus": "2-7"}
        result = _merge_cmdline(existing, desired)
        assert "isolcpus=2-7" in result
        # Should only have one isolcpus
        assert result.count("isolcpus") == 1

    def test_none_values_skipped(self):
        existing = {"quiet": ""}
        desired = {"isolcpus": None}  # Should be skipped
        result = _merge_cmdline(existing, desired)
        assert "isolcpus" not in result

    def test_empty_value_is_flag(self):
        existing = {}
        desired = {"nosmt": ""}
        result = _merge_cmdline(existing, desired)
        # Should be just "nosmt" not "nosmt="
        assert (
            result == "nosmt" or "nosmt " in result or result.endswith("nosmt")
        )

    def test_complex_merge(self):
        existing = {
            "quiet": "",
            "rhgb": "",
            "rd.lvm.lv": "alma/root",
        }
        desired = {
            "isolcpus": "2-15",
            "nohz_full": "2-15",
            "rcu_nocbs": "2-15",
            "transparent_hugepage": "never",
        }
        result = _merge_cmdline(existing, desired)
        assert "quiet" in result
        assert "isolcpus=2-15" in result
        assert "nohz_full=2-15" in result
        assert "rcu_nocbs=2-15" in result
        assert "transparent_hugepage=never" in result
