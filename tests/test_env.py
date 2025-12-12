"""Tests for environment detection and OS support."""

from unittest.mock import patch


from lltune.env import (
    OSInfo,
    detect_virtualization,
    is_root,
    is_supported_os,
    read_os_release,
)


class TestReadOsRelease:
    def test_almalinux_9(self, tmp_path):
        os_release = tmp_path / "os-release"
        os_release.write_text(
            """NAME="AlmaLinux"
VERSION="9.4 (Seafoam Ocelot)"
ID="almalinux"
ID_LIKE="rhel centos fedora"
VERSION_ID="9.4"
PLATFORM_ID="platform:el9"
PRETTY_NAME="AlmaLinux 9.4 (Seafoam Ocelot)"
"""
        )
        info = read_os_release(os_release)
        assert info is not None
        assert info.os_id == "almalinux"
        assert info.version_id == "9.4"
        assert "AlmaLinux" in info.name

    def test_rhel_9(self, tmp_path):
        os_release = tmp_path / "os-release"
        os_release.write_text(
            """NAME="Red Hat Enterprise Linux"
VERSION="9.3 (Plow)"
ID="rhel"
VERSION_ID="9.3"
PRETTY_NAME="Red Hat Enterprise Linux 9.3 (Plow)"
"""
        )
        info = read_os_release(os_release)
        assert info is not None
        assert info.os_id == "rhel"
        assert info.version_id == "9.3"

    def test_rocky_9(self, tmp_path):
        os_release = tmp_path / "os-release"
        os_release.write_text(
            """NAME="Rocky Linux"
VERSION="9.3 (Blue Onyx)"
ID="rocky"
VERSION_ID="9.3"
PRETTY_NAME="Rocky Linux 9.3 (Blue Onyx)"
"""
        )
        info = read_os_release(os_release)
        assert info is not None
        assert info.os_id == "rocky"
        assert info.version_id == "9.3"

    def test_centos_stream_9(self, tmp_path):
        os_release = tmp_path / "os-release"
        os_release.write_text(
            """NAME="CentOS Stream"
VERSION="9"
ID="centos"
VERSION_ID="9"
PLATFORM_ID="platform:el9"
PRETTY_NAME="CentOS Stream 9"
"""
        )
        info = read_os_release(os_release)
        assert info is not None
        assert info.os_id == "centos"
        assert info.version_id == "9"

    def test_oracle_linux_9(self, tmp_path):
        os_release = tmp_path / "os-release"
        os_release.write_text(
            """NAME="Oracle Linux Server"
VERSION="9.3"
ID="ol"
VERSION_ID="9.3"
PRETTY_NAME="Oracle Linux Server 9.3"
"""
        )
        info = read_os_release(os_release)
        assert info is not None
        assert info.os_id == "ol"
        assert info.version_id == "9.3"

    def test_missing_file(self, tmp_path):
        nonexistent = tmp_path / "missing"
        info = read_os_release(nonexistent)
        assert info is None

    def test_ubuntu_not_rhel(self, tmp_path):
        os_release = tmp_path / "os-release"
        os_release.write_text(
            """NAME="Ubuntu"
VERSION="22.04.3 LTS (Jammy Jellyfish)"
ID=ubuntu
VERSION_ID="22.04"
PRETTY_NAME="Ubuntu 22.04.3 LTS"
"""
        )
        info = read_os_release(os_release)
        assert info is not None
        assert info.os_id == "ubuntu"


class TestIsSupportedOs:
    def test_almalinux_9_supported(self):
        info = OSInfo(
            os_id="almalinux", version_id="9.4", name="AlmaLinux 9.4"
        )
        assert is_supported_os(info) is True

    def test_rhel_9_supported(self):
        info = OSInfo(os_id="rhel", version_id="9.3", name="RHEL 9.3")
        assert is_supported_os(info) is True

    def test_rocky_9_supported(self):
        info = OSInfo(os_id="rocky", version_id="9.2", name="Rocky 9.2")
        assert is_supported_os(info) is True

    def test_centos_9_supported(self):
        info = OSInfo(os_id="centos", version_id="9", name="CentOS Stream 9")
        assert is_supported_os(info) is True

    def test_oracle_linux_9_supported(self):
        info = OSInfo(os_id="ol", version_id="9.3", name="Oracle Linux 9.3")
        assert is_supported_os(info) is True

    def test_rhel_8_not_supported(self):
        info = OSInfo(os_id="rhel", version_id="8.9", name="RHEL 8.9")
        assert is_supported_os(info) is False

    def test_ubuntu_not_supported(self):
        info = OSInfo(os_id="ubuntu", version_id="22.04", name="Ubuntu 22.04")
        assert is_supported_os(info) is False

    def test_none_not_supported(self):
        assert is_supported_os(None) is False


class TestIsRoot:
    def test_root_detection(self):
        with patch("os.geteuid", return_value=0):
            assert is_root() is True

    def test_non_root_detection(self):
        with patch("os.geteuid", return_value=1000):
            assert is_root() is False


class TestDetectVirtualization:
    def test_no_systemd_detect_virt(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = detect_virtualization()
        assert result is None

    def test_bare_metal(self):
        mock_result = type("Result", (), {"returncode": 1, "stdout": ""})()
        with patch("subprocess.run", return_value=mock_result):
            result = detect_virtualization()
        assert result is None

    def test_kvm_detected(self):
        mock_result = type(
            "Result", (), {"returncode": 0, "stdout": "kvm\n"}
        )()
        with patch("subprocess.run", return_value=mock_result):
            result = detect_virtualization()
        assert result == "kvm"

    def test_vmware_detected(self):
        mock_result = type(
            "Result", (), {"returncode": 0, "stdout": "vmware\n"}
        )()
        with patch("subprocess.run", return_value=mock_result):
            result = detect_virtualization()
        assert result == "vmware"
