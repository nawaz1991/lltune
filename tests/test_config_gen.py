from lltune.config_gen import dump_config_yaml, generate_config_dict
from lltune.models import Snapshot
from lltune.recommendations import build_recommendations


def test_generate_config_contains_core_sections():
    snap = Snapshot()
    recs = build_recommendations(snap)
    cfg = generate_config_dict(snap, recs)
    yaml_text = dump_config_yaml(cfg, None)
    assert "cpu:" in yaml_text
    assert "memory:" in yaml_text
    assert "network:" in yaml_text
    assert "irq:" in yaml_text
    assert "safety:" in yaml_text
