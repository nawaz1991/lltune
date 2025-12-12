from types import SimpleNamespace

import yaml

from lltune.commands.audit import run_audit
from lltune.commands.gen_config import run_gen_config
from lltune.commands.scan import run_scan
from lltune.config_gen import dump_config_yaml, generate_config_dict
from lltune.models import Snapshot


def _stub_snapshot() -> Snapshot:
    snap = Snapshot()
    snap.cpu.sockets = 1
    snap.cpu.cores_per_socket = 2
    snap.cpu.threads_per_core = 2
    snap.cpu.per_cpu_governor = {0: "performance", 1: "performance"}
    return snap


def test_scan_with_stub_snapshot(monkeypatch, capsys):
    snap = _stub_snapshot()
    monkeypatch.setattr("lltune.commands.scan.collect_snapshot", lambda: snap)
    args = SimpleNamespace(format="text", output=None, md_report=None)
    rc = run_scan(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Host:" in out


def test_gen_config_and_audit_with_stub_snapshot(tmp_path, monkeypatch):
    snap = _stub_snapshot()
    snap_path = tmp_path / "snapshot.yaml"
    snap_path.write_text(yaml.safe_dump(snap.to_dict()))

    monkeypatch.setattr(
        "lltune.commands.gen_config.collect_snapshot", lambda: snap
    )
    cfg_path = tmp_path / "cfg.yaml"
    args_gen = SimpleNamespace(output=cfg_path, snapshot=snap_path)
    rc_gen = run_gen_config(args_gen)
    assert rc_gen == 0
    assert cfg_path.exists()

    cfg_data = generate_config_dict(snap)
    cfg_data["cpu"]["isolate_cores"] = "0"
    cfg_data["memory"]["hugepages"]["per_node"] = {}
    cfg_path.write_text(dump_config_yaml(cfg_data))

    args_audit = SimpleNamespace(
        config=cfg_path, snapshot=snap_path, output=None
    )
    rc_audit = run_audit(args_audit)
    assert rc_audit == 0
