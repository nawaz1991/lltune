"""Tests for sysctl and limits recommendations."""

from lltune.models import LimitsInfo, Snapshot, SysctlInfo
from lltune.recommendations import build_recommendations


def _minimal_snapshot() -> Snapshot:
    """Create a minimal snapshot for testing."""
    return Snapshot()


class TestSysctlRecommendations:
    """Tests for sysctl-related recommendations."""

    def test_busy_poll_disabled_recommendation(self):
        snap = _minimal_snapshot()
        snap.sysctl = SysctlInfo(busy_poll=0, busy_read=0)
        recs = build_recommendations(snap)
        busy_recs = [
            r for r in recs if r.item == "busy_poll" or r.item == "busy_read"
        ]
        assert len(busy_recs) == 2
        assert any("50-100" in r.target for r in busy_recs)

    def test_busy_poll_enabled_no_recommendation(self):
        snap = _minimal_snapshot()
        snap.sysctl = SysctlInfo(busy_poll=50, busy_read=50)
        recs = build_recommendations(snap)
        busy_recs = [r for r in recs if r.item in ("busy_poll", "busy_read")]
        assert len(busy_recs) == 0

    def test_tcp_timestamps_enabled_recommendation(self):
        snap = _minimal_snapshot()
        snap.sysctl = SysctlInfo(tcp_timestamps=1)
        recs = build_recommendations(snap)
        ts_recs = [r for r in recs if r.item == "tcp_timestamps"]
        assert len(ts_recs) == 1
        assert ts_recs[0].target == "0"
        assert ts_recs[0].severity == "info"

    def test_tcp_timestamps_disabled_no_recommendation(self):
        snap = _minimal_snapshot()
        snap.sysctl = SysctlInfo(tcp_timestamps=0)
        recs = build_recommendations(snap)
        ts_recs = [r for r in recs if r.item == "tcp_timestamps"]
        assert len(ts_recs) == 0

    def test_tcp_sack_enabled_recommendation(self):
        snap = _minimal_snapshot()
        snap.sysctl = SysctlInfo(tcp_sack=1)
        recs = build_recommendations(snap)
        sack_recs = [r for r in recs if r.item == "tcp_sack"]
        assert len(sack_recs) == 1
        assert sack_recs[0].target == "0"

    def test_small_rmem_max_recommendation(self):
        snap = _minimal_snapshot()
        snap.sysctl = SysctlInfo(rmem_max=212992)  # Default Linux value
        recs = build_recommendations(snap)
        rmem_recs = [r for r in recs if r.item == "rmem_max"]
        assert len(rmem_recs) == 1
        assert "67108864" in rmem_recs[0].target

    def test_large_rmem_max_no_recommendation(self):
        snap = _minimal_snapshot()
        snap.sysctl = SysctlInfo(rmem_max=67108864)  # 64MB - recommended
        recs = build_recommendations(snap)
        rmem_recs = [r for r in recs if r.item == "rmem_max"]
        assert len(rmem_recs) == 0

    def test_small_netdev_backlog_recommendation(self):
        snap = _minimal_snapshot()
        snap.sysctl = SysctlInfo(netdev_max_backlog=1000)  # Default
        recs = build_recommendations(snap)
        backlog_recs = [r for r in recs if r.item == "netdev_max_backlog"]
        assert len(backlog_recs) == 1
        assert "250000" in backlog_recs[0].target

    def test_small_somaxconn_recommendation(self):
        snap = _minimal_snapshot()
        snap.sysctl = SysctlInfo(somaxconn=128)  # Default
        recs = build_recommendations(snap)
        conn_recs = [r for r in recs if r.item == "somaxconn"]
        assert len(conn_recs) == 1
        assert "65535" in conn_recs[0].target

    def test_small_file_max_recommendation(self):
        snap = _minimal_snapshot()
        snap.sysctl = SysctlInfo(file_max=100000)
        recs = build_recommendations(snap)
        file_recs = [r for r in recs if r.item == "file_max"]
        assert len(file_recs) == 1
        assert "2097152" in file_recs[0].target

    def test_small_max_map_count_recommendation(self):
        snap = _minimal_snapshot()
        snap.sysctl = SysctlInfo(max_map_count=65530)  # Default
        recs = build_recommendations(snap)
        map_recs = [r for r in recs if r.item == "max_map_count"]
        assert len(map_recs) == 1
        assert "262144" in map_recs[0].target


class TestLimitsRecommendations:
    """Tests for resource limits recommendations."""

    def test_memlock_not_unlimited_recommendation(self):
        snap = _minimal_snapshot()
        snap.limits = LimitsInfo(memlock_soft="65536", memlock_hard="65536")
        recs = build_recommendations(snap)
        memlock_recs = [r for r in recs if r.item == "memlock"]
        assert len(memlock_recs) == 1
        assert memlock_recs[0].target == "unlimited"
        assert memlock_recs[0].severity == "warning"

    def test_memlock_unlimited_no_recommendation(self):
        snap = _minimal_snapshot()
        snap.limits = LimitsInfo(
            memlock_soft="unlimited", memlock_hard="unlimited"
        )
        recs = build_recommendations(snap)
        memlock_recs = [r for r in recs if r.item == "memlock"]
        assert len(memlock_recs) == 0

    def test_memlock_minus_one_no_recommendation(self):
        """memlock = -1 is equivalent to unlimited."""
        snap = _minimal_snapshot()
        snap.limits = LimitsInfo(memlock_soft="-1", memlock_hard="-1")
        recs = build_recommendations(snap)
        memlock_recs = [r for r in recs if r.item == "memlock"]
        assert len(memlock_recs) == 0

    def test_memlock_none_recommendation(self):
        """Missing memlock limit should trigger recommendation."""
        snap = _minimal_snapshot()
        snap.limits = LimitsInfo(memlock_soft=None, memlock_hard=None)
        recs = build_recommendations(snap)
        memlock_recs = [r for r in recs if r.item == "memlock"]
        assert len(memlock_recs) == 1

    def test_small_nofile_recommendation(self):
        snap = _minimal_snapshot()
        snap.limits = LimitsInfo(nofile_soft=1024)  # Default
        recs = build_recommendations(snap)
        nofile_recs = [r for r in recs if r.item == "nofile"]
        assert len(nofile_recs) == 1
        assert "1048576" in nofile_recs[0].target

    def test_large_nofile_no_recommendation(self):
        snap = _minimal_snapshot()
        snap.limits = LimitsInfo(nofile_soft=1048576)
        recs = build_recommendations(snap)
        nofile_recs = [r for r in recs if r.item == "nofile"]
        assert len(nofile_recs) == 0

    def test_no_limits_info_no_crash(self):
        """Ensure recommendations work even without limits info."""
        snap = _minimal_snapshot()
        snap.limits = None  # No limits info
        # Should not crash
        recs = build_recommendations(snap)
        # Will still have other recommendations
        assert isinstance(recs, list)


class TestCombinedRecommendations:
    """Tests for combined sysctl and limits recommendations."""

    def test_typical_default_system(self):
        """Test recommendations for a system with default settings."""
        snap = _minimal_snapshot()
        snap.sysctl = SysctlInfo(
            busy_poll=0,
            busy_read=0,
            tcp_timestamps=1,
            tcp_sack=1,
            rmem_max=212992,
            wmem_max=212992,
            netdev_max_backlog=1000,
            somaxconn=128,
            file_max=100000,
            max_map_count=65530,
        )
        snap.limits = LimitsInfo(
            memlock_soft="64",  # Very small
            nofile_soft=1024,
        )
        recs = build_recommendations(snap)

        # Should have recommendations for all suboptimal settings
        rec_items = [r.item for r in recs]
        assert "busy_poll" in rec_items
        assert "busy_read" in rec_items
        assert "tcp_timestamps" in rec_items
        assert "tcp_sack" in rec_items
        assert "rmem_max" in rec_items
        assert "wmem_max" in rec_items
        assert "netdev_max_backlog" in rec_items
        assert "somaxconn" in rec_items
        assert "file_max" in rec_items
        assert "max_map_count" in rec_items
        assert "memlock" in rec_items
        assert "nofile" in rec_items

    def test_well_tuned_system(self):
        """Test recommendations for a well-tuned HFT system."""
        snap = _minimal_snapshot()
        snap.sysctl = SysctlInfo(
            busy_poll=50,
            busy_read=50,
            tcp_timestamps=0,
            tcp_sack=0,
            rmem_max=67108864,
            wmem_max=67108864,
            netdev_max_backlog=250000,
            somaxconn=65535,
            file_max=2097152,
            max_map_count=262144,
        )
        snap.limits = LimitsInfo(
            memlock_soft="unlimited",
            memlock_hard="unlimited",
            nofile_soft=1048576,
            nofile_hard=1048576,
        )
        recs = build_recommendations(snap)

        # Should not have sysctl/limits recommendations
        rec_items = [r.item for r in recs]
        assert "busy_poll" not in rec_items
        assert "busy_read" not in rec_items
        assert "tcp_timestamps" not in rec_items
        assert "tcp_sack" not in rec_items
        assert "rmem_max" not in rec_items
        assert "wmem_max" not in rec_items
        assert "netdev_max_backlog" not in rec_items
        assert "somaxconn" not in rec_items
        assert "file_max" not in rec_items
        assert "max_map_count" not in rec_items
        assert "memlock" not in rec_items
        assert "nofile" not in rec_items
