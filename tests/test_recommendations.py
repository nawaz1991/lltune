from lltune.models import CpuInfo, MemoryInfo, ServicesInfo, Snapshot
from lltune.recommendations import build_recommendations


def test_governor_and_swap_and_irqbalance_recs():
    snap = Snapshot()
    snap.cpu = CpuInfo(
        per_cpu_governor={0: "powersave"}, smt_enabled=True, cmdline_flags={}
    )
    snap.memory = MemoryInfo(
        thp_enabled="always",
        swap_devices=[{"device": "swap0"}],
        numa_balancing=True,
        ksm_enabled=True,
    )
    snap.services = ServicesInfo(irqbalance_active=True)

    recs = build_recommendations(snap)
    keys = {rec.item for rec in recs}
    assert "governor" in keys
    assert "swap" in keys
    assert "irqbalance" in keys
    assert "thp_runtime" in keys
    assert "numa_balancing" in keys
    assert "ksm" in keys


def test_offload_and_coalesce_recs():
    from lltune.models import NicInfo, NicQueues

    snap = Snapshot()
    nic = NicInfo(
        name="eth0",
        offloads={
            "generic-receive-offload": "on",
            "large-receive-offload": "on",
        },
        coalescing={"rx-usecs": "10"},
    )
    nic.queues = NicQueues(rps_flow_cnt=256)
    snap.nics = [nic]

    recs = build_recommendations(snap)
    items = {rec.item for rec in recs}
    assert "eth0:offloads" in items
    assert "eth0:coalescing" in items
    assert "eth0:rps" in items


def test_time_sync_recs_when_inactive():
    snap = Snapshot()
    snap.time_sync.ntp_active = False
    snap.time_sync.chrony_active = False
    recs = build_recommendations(snap)
    items = {rec.item for rec in recs}
    assert "time_sync" in items
