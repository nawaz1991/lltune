"""Tests for PTP configuration generation."""

from lltune.ptp_config import (
    generate_ptp4l_config,
    generate_phc2sys_config,
    generate_ptp4l_service,
)


class TestPtp4lConfigGeneration:
    """Tests for ptp4l configuration generation."""

    def test_basic_config(self):
        config = generate_ptp4l_config(interface="eth0")
        assert "[global]" in config
        assert "[eth0]" in config
        assert "domainNumber" in config
        assert "time_stamping" in config
        assert "hardware" in config

    def test_domain_setting(self):
        config = generate_ptp4l_config(interface="eth0", domain=5)
        assert "domainNumber            5" in config

    def test_priority_setting(self):
        config = generate_ptp4l_config(interface="eth0", priority1=64)
        assert "priority1               64" in config

    def test_transport_l2(self):
        config = generate_ptp4l_config(interface="eth0", transport="L2")
        assert "network_transport       L2" in config

    def test_transport_udp(self):
        config = generate_ptp4l_config(interface="eth0", transport="UDPv4")
        assert "network_transport       UDPv4" in config

    def test_phc_device_in_comment(self):
        config = generate_ptp4l_config(
            interface="eth0", phc_device="/dev/ptp0"
        )
        assert "/dev/ptp0" in config


class TestPhc2sysConfigGeneration:
    """Tests for phc2sys service generation."""

    def test_basic_service(self):
        service = generate_phc2sys_config(phc_device="/dev/ptp0")
        assert "[Unit]" in service
        assert "[Service]" in service
        assert "[Install]" in service
        assert "/dev/ptp0" in service

    def test_sync_interval(self):
        service = generate_phc2sys_config(
            phc_device="/dev/ptp0",
            sync_interval=0.5,
        )
        assert "-R 2" in service  # 1/0.5 = 2 Hz

    def test_after_ptp4l(self):
        service = generate_phc2sys_config(phc_device="/dev/ptp0")
        assert "After=lltune-ptp4l.service" in service
        assert "Requires=lltune-ptp4l.service" in service


class TestPtp4lServiceGeneration:
    """Tests for ptp4l systemd service generation."""

    def test_basic_service(self):
        service = generate_ptp4l_service(
            interface="eth0",
            config_path="/etc/ptp/ptp4l.conf",
        )
        assert "[Unit]" in service
        assert "[Service]" in service
        assert "[Install]" in service
        assert "eth0" in service
        assert "/etc/ptp/ptp4l.conf" in service

    def test_execstart_command(self):
        service = generate_ptp4l_service(
            interface="eth0",
            config_path="/etc/ptp/ptp4l.conf",
        )
        assert "ExecStart=/usr/sbin/ptp4l" in service
        assert "-f /etc/ptp/ptp4l.conf" in service
        assert "-i eth0" in service

    def test_restart_on_failure(self):
        service = generate_ptp4l_service(
            interface="eth0",
            config_path="/etc/ptp/ptp4l.conf",
        )
        assert "Restart=on-failure" in service
