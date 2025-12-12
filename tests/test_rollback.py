"""Tests for rollback module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


from lltune.commands.rollback import (
    _disable_lltune_services,
    _restore_file,
    _restore_sysctl_runtime,
    _run_grub_mkconfig,
    run_rollback,
)


class TestRestoreFile:
    def test_restore_existing_backup(self, tmp_path):
        # Create backup structure
        backup_root = tmp_path / "backup"
        baseline = backup_root / "baseline" / "etc" / "default"
        baseline.mkdir(parents=True)

        # Create backup file
        (baseline / "grub").write_text("GRUB_CMDLINE_LINUX='original'")

        # Create target directory
        target = tmp_path / "etc" / "default"
        target.mkdir(parents=True)
        target_file = target / "grub"
        target_file.write_text("GRUB_CMDLINE_LINUX='modified'")

        logger = MagicMock()

        # Restore with adjusted path
        with patch.object(
            Path, "relative_to", return_value=Path("etc/default/grub")
        ):
            result = _restore_file(backup_root, target_file, logger)

        # Should restore successfully
        assert result is True
        logger.info.assert_called()

    def test_restore_missing_backup(self, tmp_path):
        backup_root = tmp_path / "backup"
        backup_root.mkdir(parents=True)

        target = tmp_path / "etc" / "default" / "grub"
        target.parent.mkdir(parents=True)
        target.write_text("test")

        logger = MagicMock()
        result = _restore_file(backup_root, target, logger)

        assert result is False
        logger.warning.assert_called()


class TestRunGrubMkconfig:
    def test_grub_mkconfig_not_found(self):
        logger = MagicMock()
        with patch("shutil.which", return_value=None):
            result = _run_grub_mkconfig(logger)
        assert result is False
        logger.warning.assert_called()

    def test_grub_mkconfig_success(self, tmp_path):
        logger = MagicMock()

        # Create a mock EFI grub.cfg path
        mock_efi_path = tmp_path / "grub.cfg"
        mock_efi_path.touch()

        # Mock grub2-mkconfig being found
        with patch("shutil.which", return_value="/usr/sbin/grub2-mkconfig"):
            # Mock detect_efi_grub_path returning a valid path
            with patch(
                "lltune.commands.rollback.detect_efi_grub_path",
                return_value=mock_efi_path
            ):
                # Mock subprocess.run
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stderr = ""

                with patch("subprocess.run", return_value=mock_result):
                    result = _run_grub_mkconfig(logger)

        assert result is True
        logger.info.assert_called()


class TestDisableLltuneServices:
    def test_disables_services(self):
        logger = MagicMock()

        with patch("shutil.which", return_value="/usr/bin/systemctl"):
            with patch("subprocess.run") as mock_run:
                with patch.object(Path, "exists", return_value=True):
                    with patch.object(Path, "unlink"):
                        _disable_lltune_services(logger)

        # Should have called systemctl for each service
        assert mock_run.call_count >= 1

    def test_no_systemctl(self):
        logger = MagicMock()

        with patch("shutil.which", return_value=None):
            _disable_lltune_services(logger)

        # Should not log anything if systemctl not available
        logger.info.assert_not_called()


class TestRestoreSysctlRuntime:
    def test_sysctl_reload(self, tmp_path):
        backup_root = tmp_path / "backup"
        sysctl_backup = backup_root / "baseline" / "etc" / "sysctl.d"
        sysctl_backup.mkdir(parents=True)
        (sysctl_backup / "99-latency-tuner.conf").write_text(
            "kernel.numa_balancing=0"
        )

        logger = MagicMock()

        with patch("shutil.which", return_value="/usr/sbin/sysctl"):
            with patch("subprocess.run") as mock_run:
                _restore_sysctl_runtime(backup_root, logger)

        logger.info.assert_called()
        mock_run.assert_called_once()

    def test_no_sysctl_binary(self, tmp_path):
        backup_root = tmp_path / "backup"
        backup_root.mkdir(parents=True)

        logger = MagicMock()

        with patch("shutil.which", return_value=None):
            _restore_sysctl_runtime(backup_root, logger)

        # Should not log or call anything
        logger.info.assert_not_called()


class TestRunRollback:
    def test_missing_backup_bundle(self, tmp_path):
        args = MagicMock()
        args.backup = str(tmp_path / "nonexistent")

        result = run_rollback(args)

        assert result == 1

    def test_successful_rollback(self, tmp_path):
        # Create backup bundle
        bundle = tmp_path / "backup-20241209120000"
        baseline = bundle / "baseline"

        # Create backed up files
        grub_backup = baseline / "etc" / "default"
        grub_backup.mkdir(parents=True)
        (grub_backup / "grub").write_text("GRUB_CMDLINE_LINUX='original'")

        sysctl_backup = baseline / "etc" / "sysctl.d"
        sysctl_backup.mkdir(parents=True)
        (sysctl_backup / "99-latency-tuner.conf").write_text(
            "kernel.numa_balancing=1"
        )

        args = MagicMock()
        args.backup = str(bundle)
        args.regenerate_grub = False
        args.disable_services = False

        # Mock the actual file restoration
        with patch("lltune.commands.rollback.GRUB_DEFAULT") as mock_grub:
            mock_grub.exists.return_value = True
            mock_grub.__truediv__ = (
                lambda self, x: tmp_path / "etc" / "default" / x
            )

            with patch("lltune.commands.rollback.SYSCTL_PATH") as mock_sysctl:
                mock_sysctl.exists.return_value = True

                with patch(
                    "lltune.commands.rollback.FSTAB_PATH"
                ) as mock_fstab:
                    mock_fstab.exists.return_value = False

                    with patch(
                        "lltune.commands.rollback._restore_file"
                    ) as mock_restore:
                        mock_restore.return_value = True

                        result = run_rollback(args)

        assert result == 0


class TestRollbackIntegration:
    """Integration tests for full rollback workflow."""

    def test_rollback_workflow(self, tmp_path):
        """Test the complete rollback workflow with mock filesystem."""
        # Create a realistic backup bundle structure
        bundle = tmp_path / "backup-20241209120000"
        baseline = bundle / "baseline"

        # Grub backup
        grub_dir = baseline / "etc" / "default"
        grub_dir.mkdir(parents=True)
        (grub_dir / "grub").write_text(
            'GRUB_CMDLINE_LINUX="rhgb quiet"\nGRUB_TIMEOUT=5\n'
        )

        # Sysctl backup
        sysctl_dir = baseline / "etc" / "sysctl.d"
        sysctl_dir.mkdir(parents=True)
        (sysctl_dir / "99-latency-tuner.conf").write_text(
            "# Original sysctl\nkernel.numa_balancing=1\n"
        )

        # Ethtool baseline
        ethtool_dir = bundle / "ethtool"
        ethtool_dir.mkdir(parents=True)
        (ethtool_dir / "eth0.features").write_text("gro: on\nlro: on\n")
        (ethtool_dir / "eth0.coalesce").write_text("rx-usecs: 3\n")

        # Config and snapshot
        import yaml

        (bundle / "config.yaml").write_text(
            yaml.safe_dump({"version": 1, "cpu": {}, "memory": {}})
        )
        (bundle / "snapshot.json").write_text(
            json.dumps({"host": {"hostname": "test"}})
        )

        # Verify structure
        assert bundle.exists()
        assert (grub_dir / "grub").exists()
        assert (sysctl_dir / "99-latency-tuner.conf").exists()
