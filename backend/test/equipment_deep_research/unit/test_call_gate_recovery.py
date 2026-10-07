from equipment_deep_research.agents.performance import AdaptiveCallGate


def _complete(gate, *, success=True, elapsed=300.0):
    assert gate.try_acquire(priority="critical") is not None
    gate.release(elapsed, success=success)


def _gate(monkeypatch):
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY", "6")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MIN", "2")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX", "8")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_LATENCY_DOWNSHIFT", "0")
    return AdaptiveCallGate()


def test_failed_window_is_not_counted_again_on_success(monkeypatch):
    gate = _gate(monkeypatch)
    for success in (True, True, False, False):
        _complete(gate, success=success)
    assert gate.limit == 5
    for _ in range(3):
        _complete(gate)
        assert gate.limit == 5
    _complete(gate)
    assert gate.limit == 6
    for _ in range(8):
        _complete(gate)
    assert gate.limit == 6


def test_new_failure_window_still_reduces_concurrency(monkeypatch):
    gate = _gate(monkeypatch)
    for expected in (5, 4, 3, 2, 2):
        for _ in range(4):
            _complete(gate, success=False)
        assert gate.limit == expected


def test_explicit_latency_downshift_does_not_recover_on_slow_calls(monkeypatch):
    gate = _gate(monkeypatch)
    gate.latency_downshift_enabled = True
    for _ in range(8):
        _complete(gate)
    assert gate.limit == 4
    for _ in range(4):
        _complete(gate, elapsed=1)
    assert gate.limit == 5


def test_reconfiguration_discards_old_failure_samples(monkeypatch):
    gate = _gate(monkeypatch)
    for _ in range(3):
        _complete(gate, success=False)
    gate.configure_concurrency(4)
    _complete(gate)
    assert gate.limit == 4
