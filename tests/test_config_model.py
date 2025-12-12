from lltune.config_model import validate_cross, validate_schema


def test_schema_rejects_unknown_and_missing_version():
    res_missing = validate_schema({"cpu": {}})
    assert any(
        i.field == "version" and i.severity == "error"
        for i in res_missing.issues
    )

    res_unknown = validate_schema({"version": 1, "badkey": {}})
    assert any(
        i.field == "badkey" and i.severity == "error"
        for i in res_unknown.issues
    )


def test_cross_validation_checks_cpus_and_nics_and_hugepages():
    cfg = {
        "version": 1,
        "cpu": {"isolate_cores": "0,5"},
        "memory": {"hugepages": {"total": "2"}},
        "network": {"interfaces": [{"name": "eth9"}]},
    }
    snapshot = {
        "cpu": {"per_cpu_governor": {"0": "performance", "1": "performance"}},
        "memory": {"total_kb": 1024},
        "nics": [{"name": "eth0"}],
    }
    res = validate_cross(cfg, snapshot)
    fields = {i.field: i.severity for i in res.issues}
    assert (
        "cpu.isolate_cores" in fields
        and fields["cpu.isolate_cores"] == "error"
    )
    assert (
        "memory.hugepages.total" in fields
        and fields["memory.hugepages.total"] == "error"
    )
    assert (
        "network.interfaces.eth9" in fields
        and fields["network.interfaces.eth9"] == "error"
    )
