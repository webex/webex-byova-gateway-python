from byova_e2e.state import PromptGate


def test_prompt_gate_requires_observed_remote_audio() -> None:
    gate = PromptGate(silence_seconds=0.75)

    gate.remote_audio_inactive(1.0)

    assert not gate.ready_to_inject(10.0)


def test_prompt_gate_releases_after_configured_quiet_interval() -> None:
    gate = PromptGate(silence_seconds=0.75)
    gate.remote_audio_active()
    gate.remote_audio_inactive(10.0)

    assert not gate.ready_to_inject(10.749)
    assert gate.ready_to_inject(10.75)


def test_new_remote_audio_cancels_pending_injection() -> None:
    gate = PromptGate(silence_seconds=0.75)
    gate.remote_audio_active()
    gate.remote_audio_inactive(10.0)
    gate.remote_audio_active()

    assert not gate.ready_to_inject(20.0)
    gate.remote_audio_inactive(20.0)
    assert gate.ready_to_inject(20.75)


def test_prompt_gate_injects_only_once() -> None:
    gate = PromptGate(silence_seconds=0.75)
    gate.remote_audio_active()
    gate.remote_audio_inactive(10.0)
    gate.mark_injected()

    assert not gate.ready_to_inject(20.0)


def test_prompt_gate_can_skip_contact_center_ringback() -> None:
    gate = PromptGate(silence_seconds=0.75, target_prompt_occurrence=2)
    gate.remote_audio_active()
    gate.remote_audio_inactive(10.0)

    assert not gate.ready_to_inject(10.75)
    assert gate.completed_prompt_count == 1

    gate.remote_audio_active()
    gate.remote_audio_inactive(20.0)

    assert gate.ready_to_inject(20.75)
    assert gate.completed_prompt_count == 2
