import json

from lltune.discovery import _parse_cpulist, parse_cmdline
from lltune.models import Snapshot


def test_parse_cpulist_ranges():
    assert _parse_cpulist("0-3,8,10-11") == [0, 1, 2, 3, 8, 10, 11]
    assert _parse_cpulist("") == []
    assert _parse_cpulist("foo,1") == [1]


def test_parse_cmdline_basic(tmp_path):
    path = tmp_path / "cmdline"
    path.write_text("isolcpus=1-3 nohz_full=1-3 mitigations=off")
    parsed = parse_cmdline(path)
    assert parsed["isolcpus"] == "1-3"
    assert parsed["nohz_full"] == "1-3"
    assert parsed["mitigations"] == "off"


def test_snapshot_serializes_datetime():
    snap = Snapshot()
    snap_dict = snap.to_dict()
    assert "collected_at" in snap_dict["host"]
    json.dumps(snap_dict)  # must not raise
