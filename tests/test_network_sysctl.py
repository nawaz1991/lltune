"""Tests for network sysctl tuning."""

from lltune.apply_engine import _sysctl_lines
from lltune.models import LimitsInfo, SysctlInfo
from lltune.persistence import _render_limits_conf


class TestNetworkSysctlLines:
    """Tests for network sysctl configuration generation."""

    def test_busy_poll_settings(self):
        cfg = {
            "network": {
                "sysctl": {
                    "busy_poll": 50,
                    "busy_read": 50,
                }
            }
        }
        lines = _sysctl_lines(cfg)
        assert "net.core.busy_poll=50" in lines
        assert "net.core.busy_read=50" in lines

    def test_tcp_timestamps_disabled(self):
        cfg = {
            "network": {
                "sysctl": {
                    "tcp_timestamps": False,
                }
            }
        }
        lines = _sysctl_lines(cfg)
        assert "net.ipv4.tcp_timestamps=0" in lines

    def test_tcp_timestamps_enabled(self):
        cfg = {
            "network": {
                "sysctl": {
                    "tcp_timestamps": True,
                }
            }
        }
        lines = _sysctl_lines(cfg)
        assert "net.ipv4.tcp_timestamps=1" in lines

    def test_tcp_sack_disabled(self):
        cfg = {
            "network": {
                "sysctl": {
                    "tcp_sack": False,
                }
            }
        }
        lines = _sysctl_lines(cfg)
        assert "net.ipv4.tcp_sack=0" in lines

    def test_buffer_sizes(self):
        cfg = {
            "network": {
                "sysctl": {
                    "rmem_max": 67108864,
                    "wmem_max": 67108864,
                    "tcp_rmem": "4096 87380 67108864",
                    "tcp_wmem": "4096 65536 67108864",
                }
            }
        }
        lines = _sysctl_lines(cfg)
        assert "net.core.rmem_max=67108864" in lines
        assert "net.core.wmem_max=67108864" in lines
        assert "net.ipv4.tcp_rmem=4096 87380 67108864" in lines
        assert "net.ipv4.tcp_wmem=4096 65536 67108864" in lines

    def test_backlog_settings(self):
        cfg = {
            "network": {
                "sysctl": {
                    "netdev_max_backlog": 250000,
                    "somaxconn": 65535,
                }
            }
        }
        lines = _sysctl_lines(cfg)
        assert "net.core.netdev_max_backlog=250000" in lines
        assert "net.core.somaxconn=65535" in lines

    def test_low_latency_tcp(self):
        cfg = {
            "network": {
                "sysctl": {
                    "tcp_low_latency": True,
                    "tcp_tw_reuse": True,
                    "tcp_fin_timeout": 15,
                    "tcp_fastopen": 3,
                }
            }
        }
        lines = _sysctl_lines(cfg)
        assert "net.ipv4.tcp_low_latency=1" in lines
        assert "net.ipv4.tcp_tw_reuse=1" in lines
        assert "net.ipv4.tcp_fin_timeout=15" in lines
        assert "net.ipv4.tcp_fastopen=3" in lines

    def test_file_max(self):
        cfg = {
            "network": {
                "sysctl": {
                    "file_max": 2097152,
                }
            }
        }
        lines = _sysctl_lines(cfg)
        assert "fs.file-max=2097152" in lines

    def test_memory_vm_settings(self):
        cfg = {
            "memory": {
                "dirty_ratio": 10,
                "dirty_background_ratio": 5,
                "mlock": {
                    "max_map_count": 262144,
                },
            }
        }
        lines = _sysctl_lines(cfg)
        assert "vm.dirty_ratio=10" in lines
        assert "vm.dirty_background_ratio=5" in lines
        assert "vm.max_map_count=262144" in lines

    def test_combined_settings(self):
        """Test combining memory and network sysctl settings."""
        cfg = {
            "memory": {
                "numa_balancing": False,
                "swap_disable": True,
            },
            "network": {
                "sysctl": {
                    "busy_poll": 50,
                    "tcp_timestamps": False,
                }
            },
        }
        lines = _sysctl_lines(cfg)
        assert "kernel.numa_balancing=0" in lines
        assert "vm.swappiness=0" in lines
        assert "net.core.busy_poll=50" in lines
        assert "net.ipv4.tcp_timestamps=0" in lines

    def test_empty_sysctl_section(self):
        cfg = {"network": {"sysctl": {}}}
        lines = _sysctl_lines(cfg)
        # Should not include any network sysctl lines
        assert not any("net.core" in line for line in lines)
        assert not any("net.ipv4" in line for line in lines)


class TestSysctlInfoDataclass:
    """Tests for SysctlInfo dataclass."""

    def test_default_values(self):
        sysctl = SysctlInfo()
        assert sysctl.rmem_max is None
        assert sysctl.busy_poll is None
        assert sysctl.tcp_timestamps is None

    def test_with_values(self):
        sysctl = SysctlInfo(
            rmem_max=67108864,
            busy_poll=50,
            tcp_timestamps=0,
        )
        assert sysctl.rmem_max == 67108864
        assert sysctl.busy_poll == 50
        assert sysctl.tcp_timestamps == 0


class TestLimitsInfoDataclass:
    """Tests for LimitsInfo dataclass."""

    def test_default_values(self):
        limits = LimitsInfo()
        assert limits.memlock_soft is None
        assert limits.nofile_soft is None

    def test_with_values(self):
        limits = LimitsInfo(
            memlock_soft="unlimited",
            memlock_hard="unlimited",
            nofile_soft=1048576,
            nofile_hard=1048576,
        )
        assert limits.memlock_soft == "unlimited"
        assert limits.nofile_soft == 1048576


class TestLimitsConfGeneration:
    """Tests for limits.conf file generation."""

    def test_basic_memlock(self):
        memory_cfg = {
            "mlock": {
                "enabled": True,
                "soft": "unlimited",
                "hard": "unlimited",
            }
        }
        content = _render_limits_conf(memory_cfg)
        assert "*    -    memlock    unlimited" in content

    def test_memlock_with_user(self):
        memory_cfg = {
            "mlock": {
                "enabled": True,
                "user": "trading",
                "soft": "unlimited",
                "hard": "unlimited",
            }
        }
        content = _render_limits_conf(memory_cfg)
        assert "trading    -    memlock    unlimited" in content

    def test_memlock_different_soft_hard(self):
        memory_cfg = {
            "mlock": {
                "enabled": True,
                "soft": "64000000",
                "hard": "unlimited",
            }
        }
        content = _render_limits_conf(memory_cfg)
        assert "*    soft    memlock    64000000" in content
        assert "*    hard    memlock    unlimited" in content

    def test_nofile_limit(self):
        memory_cfg = {
            "limits": {
                "nofile": 1048576,
            }
        }
        content = _render_limits_conf(memory_cfg)
        assert "*    -    nofile    1048576" in content

    def test_nproc_limit(self):
        memory_cfg = {
            "limits": {
                "nproc": 65536,
            }
        }
        content = _render_limits_conf(memory_cfg)
        assert "*    -    nproc    65536" in content

    def test_rtprio_limit(self):
        memory_cfg = {
            "limits": {
                "rtprio": 99,
            }
        }
        content = _render_limits_conf(memory_cfg)
        assert "*    -    rtprio    99" in content

    def test_combined_limits(self):
        memory_cfg = {
            "mlock": {
                "enabled": True,
                "user": "*",
                "soft": "unlimited",
                "hard": "unlimited",
            },
            "limits": {
                "nofile": 1048576,
                "nproc": 65536,
                "rtprio": 99,
            },
        }
        content = _render_limits_conf(memory_cfg)
        assert "memlock" in content
        assert "nofile" in content
        assert "nproc" in content
        assert "rtprio" in content

    def test_empty_config(self):
        memory_cfg = {}
        content = _render_limits_conf(memory_cfg)
        # Should have header but no limit lines
        assert "LLTune resource limits configuration" in content
        assert "memlock" not in content.split("Format:")[1]  # After header
