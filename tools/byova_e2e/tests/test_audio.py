import numpy as np
import soundfile as sf
import pytest

from byova_e2e.audio import AudioPreparationError, TARGET_SAMPLE_RATE, prepare_wav, render_text


def test_prepare_wav_downmixes_and_resamples(tmp_path) -> None:
    source = tmp_path / "stereo-8khz.wav"
    destination = tmp_path / "prepared.wav"
    samples = np.column_stack((np.ones(8_000), -np.ones(8_000)))
    sf.write(source, samples, 8_000, subtype="PCM_16")

    prepared = prepare_wav(source, destination)
    data, sample_rate = sf.read(destination, always_2d=True)

    assert sample_rate == TARGET_SAMPLE_RATE
    assert data.shape == (16_000, 1)
    assert prepared.duration_seconds == 1.0
    assert len(prepared.sha256) == 64


def test_render_text_normalises_macos_say_output(tmp_path, monkeypatch) -> None:
    def fake_say(command, **_kwargs):
        output = command[command.index("-o") + 1]
        sf.write(output, np.ones(8_000), 8_000, format="AIFF", subtype="PCM_16")
        return __import__("subprocess").CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("byova_e2e.audio.subprocess.run", fake_say)
    prepared = render_text("test", "Samantha", tmp_path / "caller.wav")

    samples, sample_rate = sf.read(prepared.path, always_2d=True)
    assert sample_rate == TARGET_SAMPLE_RATE
    assert samples.shape == (16_000, 1)


def test_render_text_reports_macos_say_failure(tmp_path, monkeypatch) -> None:
    def failed_say(command, **_kwargs):
        return __import__("subprocess").CompletedProcess(command, 1, "", "Unknown voice")

    monkeypatch.setattr("byova_e2e.audio.subprocess.run", failed_say)

    with pytest.raises(AudioPreparationError, match="could not render"):
        render_text("test", "unknown", tmp_path / "caller.wav")
