from backend.app.resource_guard import ResourceGuard


def transition_kinds(guard: ResourceGuard, cpu: float, memory: float, now: float) -> list[str]:
    return [item.kind for item in guard.observe(cpu, memory, now=now)]


def test_cpu_pause_and_resume_require_strict_sustained_thresholds() -> None:
    guard = ResourceGuard()

    assert transition_kinds(guard, 51, 30, 0) == []
    assert transition_kinds(guard, 50, 30, 9) == []
    assert transition_kinds(guard, 75, 30, 10) == []
    assert transition_kinds(guard, 75, 30, 20) == ["cpu_pause"]
    assert guard.cpu_paused is True

    assert transition_kinds(guard, 30, 30, 21) == []
    assert transition_kinds(guard, 29, 30, 22) == []
    assert transition_kinds(guard, 29, 30, 32) == ["cpu_resume"]
    assert guard.cpu_paused is False


def test_cpu_spike_does_not_accumulate_across_recovery_samples() -> None:
    guard = ResourceGuard()

    assert transition_kinds(guard, 90, 30, 0) == []
    assert transition_kinds(guard, 20, 30, 9) == []
    assert transition_kinds(guard, 90, 30, 10) == []
    assert transition_kinds(guard, 90, 30, 19.9) == []


def test_memory_admission_gate_changes_immediately_and_uses_strict_limit() -> None:
    guard = ResourceGuard()

    assert transition_kinds(guard, 10, 70, 0) == []
    assert transition_kinds(guard, 10, 70.1, 1) == ["memory_block"]
    assert guard.admission_blocked is True
    assert transition_kinds(guard, 10, 70, 2) == ["memory_resume"]
    assert guard.admission_blocked is False
