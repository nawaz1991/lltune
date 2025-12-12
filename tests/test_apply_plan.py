"""Tests for apply engine planning and execution."""

from unittest.mock import patch


from lltune.apply_engine import (
    _apply_irq,
    _apply_nic,
    _apply_rps_rfs,
    _apply_services,
    _apply_sysctl,
    _merge_cmdline,
    _sysctl_lines,
    apply_config,
    plan_apply,
)
from lltune.utils import cpus_to_mask, parse_cpulist


class TestCpulistParsing:
    def test_single_cpu(self):
        assert parse_cpulist("0") == [0]
        assert parse_cpulist("5") == [5]

    def test_range(self):
        assert parse_cpulist("0-3") == [0, 1, 2, 3]

    def test_mixed(self):
        assert parse_cpulist("0-2,5,8-10") == [0, 1, 2, 5, 8, 9, 10]

    def test_empty(self):
        assert parse_cpulist("") == []


class TestCpusToMask:
    def test_single_cpu(self):
        assert cpus_to_mask([0]) == "1"
        assert cpus_to_mask([1]) == "2"
        assert cpus_to_mask([3]) == "8"

    def test_multiple_cpus(self):
        assert cpus_to_mask([0, 1]) == "3"
        assert cpus_to_mask([0, 1, 2, 3]) == "f"

    def test_empty(self):
        assert cpus_to_mask([]) == "0"


class TestMergeCmdline:
    def test_basic_merge(self):
        existing = {"quiet": "", "mitigations": "auto"}
        desired = {"isolcpus": "1-3", "nohz_full": "1-3"}
        result = _merge_cmdline(existing, desired)
        assert "quiet" in result
        assert "isolcpus=1-3" in result
        assert "nohz_full=1-3" in result

    def test_override(self):
        existing = {"mitigations": "auto"}
        desired = {"mitigations": "off"}
        result = _merge_cmdline(existing, desired)
        assert "mitigations=off" in result
        assert "mitigations=auto" not in result


class TestSysctlLines:
    def test_numa_balancing(self):
        cfg = {"memory": {"numa_balancing": False}}
        lines = _sysctl_lines(cfg)
        assert "kernel.numa_balancing=0" in lines

    def test_swap_disable(self):
        cfg = {"memory": {"swap_disable": True}}
        lines = _sysctl_lines(cfg)
        assert "vm.swappiness=0" in lines

    def test_ksm(self):
        cfg = {"memory": {"ksm": False}}
        lines = _sysctl_lines(cfg)
        assert "vm.ksm_run=0" in lines


def test_plan_apply_creates_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("LLTUNE_BACKUP_ROOT", str(tmp_path))
    cfg = {
        "version": 1,
        "cpu": {"isolate_cores": "0-1"},
        "memory": {},
        "network": {"interfaces": []},
    }
    # Mock collect_snapshot to return a snapshot with CPUs 0-1 available
    from lltune.models import Snapshot, CpuInfo
    mock_snapshot = Snapshot(
        cpu=CpuInfo(per_cpu_governor={
            0: "performance", 1: "performance",
            2: "performance", 3: "performance"
        }),
    )
    with patch("lltune.apply_engine.collect_snapshot", return_value=mock_snapshot):
        plan, errors = plan_apply(cfg, backup_root=tmp_path)
    assert not errors
    assert plan.backup_dir.exists()
    assert any(plan.backup_dir.iterdir())
    assert any(s.detail for s in plan.steps)
    assert plan.persistence["root"].exists()


def test_persistence_artifacts_written(tmp_path, monkeypatch):
    monkeypatch.setenv("LLTUNE_BACKUP_ROOT", str(tmp_path))
    cfg = {
        "version": 1,
        "memory": {
            "thp_runtime": "never",
            "hugepages": {"size_kb": 2048, "total": 64},
        },
        "network": {"defaults": {"disable_gro": True}, "interfaces": []},
    }
    plan, errors = plan_apply(cfg, backup_root=tmp_path)
    assert not errors
    root = plan.persistence["root"]
    nic_script = plan.persistence["nic_script"]
    thp_script = plan.persistence["thp_script"]
    assert (root / "README.txt").exists()
    assert (root / "lltune-nic-restore.service").exists()
    assert (root / "lltune-thp-setup.service").exists()
    assert nic_script.read_text().strip().startswith("#!/bin/bash")
    assert thp_script.read_text().strip().startswith("#!/bin/bash")


def test_plan_apply_blocks_grub_changes_when_disallowed(tmp_path, monkeypatch):
    monkeypatch.setenv("LLTUNE_BACKUP_ROOT", str(tmp_path))
    cfg = {
        "version": 1,
        "kernel": {"cmdline": {"isolcpus": "0-1"}},
        "safety": {"allow_grub_edit": False},
        "memory": {},
        "network": {"interfaces": []},
    }
    plan, errors = plan_apply(cfg, backup_root=tmp_path)
    assert not errors
    assert plan.reboot_required is False


def test_apply_nic_handles_coalesce_and_rings_plan_only(tmp_path):
    cfg = {
        "network": {
            "defaults": {"disable_gro": True},
            "interfaces": [
                {
                    "name": "eth0",
                    "coalescing": {"rx_usecs": 0, "tx_usecs": 0},
                    "rings": {"rx": 4096, "tx": 4096},
                    "flow_control": {"rx": False, "tx": True},
                    "queues": {"combined": 4},
                }
            ],
        }
    }
    res = _apply_nic(cfg, tmp_path, plan_only=True)
    detail = res.detail
    assert "coalescing" in detail
    assert "rings" in detail
    assert "flow" in detail
    assert "queues" in detail


class TestApplyServices:
    def test_disable_irqbalance(self, tmp_path):
        cfg = {"services": {"irqbalance": False}}
        with patch("lltune.apply_engine.run_cmd") as mock_run:
            res = _apply_services(cfg, tmp_path, plan_only=False)
        assert "irqbalance" in res.detail
        mock_run.assert_called()

    def test_set_tuned_profile(self, tmp_path):
        cfg = {"services": {"tuned": "latency-performance"}}
        with patch("lltune.apply_engine.run_cmd") as mock_run:
            res = _apply_services(cfg, tmp_path, plan_only=False)
        assert "tuned" in res.detail
        mock_run.assert_called()

    def test_plan_only_no_execution(self, tmp_path):
        cfg = {"services": {"irqbalance": False}}
        with patch("lltune.apply_engine.run_cmd") as mock_run:
            _res = _apply_services(cfg, tmp_path, plan_only=True)  # noqa: F841
        mock_run.assert_not_called()


class TestApplySysctl:
    def test_writes_sysctl_file(self, tmp_path):
        cfg = {"memory": {"numa_balancing": False, "swap_disable": True}}
        # Mock SYSCTL_PATH to use a temp directory
        mock_sysctl_path = (
            tmp_path / "etc" / "sysctl.d" / "99-latency-tuner.conf"
        )
        mock_sysctl_path.parent.mkdir(parents=True, exist_ok=True)
        with patch("lltune.apply_engine.SYSCTL_PATH", mock_sysctl_path):
            with patch("lltune.apply_engine.run_cmd"):
                res = _apply_sysctl(cfg, tmp_path, plan_only=False)
        assert res.ok
        assert "entries" in res.detail
        # Verify the file was written
        assert mock_sysctl_path.exists()
        content = mock_sysctl_path.read_text()
        assert "kernel.numa_balancing=0" in content

    def test_no_entries(self, tmp_path):
        cfg = {"memory": {}}
        res = _apply_sysctl(cfg, tmp_path, plan_only=True)
        assert res.ok
        assert "no sysctl entries" in res.detail


class TestApplyIrq:
    def test_no_affinity_rules(self, tmp_path):
        cfg = {"irq": {}}
        res = _apply_irq(cfg, tmp_path, plan_only=True)
        assert res.ok
        assert "no affinity rules" in res.detail


class TestApplyRpsRfs:
    def test_not_configured(self, tmp_path):
        cfg = {"irq": {}}
        snapshot = {"nics": [{"name": "eth0"}]}
        res = _apply_rps_rfs(cfg, snapshot, tmp_path, plan_only=True)
        assert res.ok
        assert "not configured" in res.detail

    def test_disable_rps(self, tmp_path):
        cfg = {
            "irq": {"disable_rps": True},
            "network": {"interfaces": [{"name": "eth0"}]},
        }
        snapshot = {"nics": [{"name": "eth0"}]}

        # Create fake sysfs structure
        queues_dir = (
            tmp_path / "sys" / "class" / "net" / "eth0" / "queues" / "rx-0"
        )
        queues_dir.mkdir(parents=True)
        (queues_dir / "rps_cpus").write_text("f")
        (queues_dir / "rps_flow_cnt").write_text("256")

        with patch(
            "lltune.apply_engine.Path",
            return_value=tmp_path
            / "sys"
            / "class"
            / "net"
            / "eth0"
            / "queues",
        ):
            res = _apply_rps_rfs(cfg, snapshot, tmp_path, plan_only=True)

        assert res.ok


class TestApplyConfig:
    def test_apply_skips_grub_when_disallowed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLTUNE_BACKUP_ROOT", str(tmp_path))
        cfg = {
            "version": 1,
            "kernel": {"cmdline": {"isolcpus": "1-3"}},
            "safety": {"allow_grub_edit": False},
            "memory": {},
            "network": {"interfaces": []},
        }
        result = apply_config(cfg, plan_only=False, backup_root=tmp_path)
        assert result.ok
        assert not result.errors

    def test_apply_plan_only_no_system_changes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLTUNE_BACKUP_ROOT", str(tmp_path))
        cfg = {
            "version": 1,
            "memory": {"numa_balancing": False},
            "network": {"interfaces": []},
        }
        result = apply_config(cfg, plan_only=True, backup_root=tmp_path)
        assert result.ok


class TestRebootRequired:
    def test_plan_indicates_reboot_required_for_kernel_cmdline(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("LLTUNE_BACKUP_ROOT", str(tmp_path))
        cfg = {
            "version": 1,
            "kernel": {"cmdline": {"isolcpus": "1-3"}},
            "safety": {"allow_grub_edit": True},
            "memory": {},
            "network": {"interfaces": []},
        }
        plan, errors = plan_apply(cfg, backup_root=tmp_path)
        assert not errors
        assert plan.reboot_required is True

    def test_plan_no_reboot_without_kernel_changes(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("LLTUNE_BACKUP_ROOT", str(tmp_path))
        cfg = {
            "version": 1,
            "memory": {"numa_balancing": False},
            "network": {"interfaces": []},
        }
        plan, errors = plan_apply(cfg, backup_root=tmp_path)
        assert not errors
        assert plan.reboot_required is False
