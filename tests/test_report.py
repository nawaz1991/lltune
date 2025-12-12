from lltune.discovery import collect_snapshot
from lltune.report import render_markdown


def test_markdown_contains_core_sections():
    snap = collect_snapshot().to_dict()
    md = render_markdown(snap, reboot_required=False)
    assert "# LLTune Scan Report" in md
    assert "CPU & NUMA" in md
    assert "Memory" in md
    assert "NICs" in md
    assert "Time & Services" in md
