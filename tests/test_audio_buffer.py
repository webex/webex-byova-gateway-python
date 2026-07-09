from unittest.mock import Mock

from src.utils.audio_buffer import AudioBuffer


def test_audio_buffer_only_stores_bytes():
    buffer = AudioBuffer("conv", max_buffer_size=5)
    assert buffer.append(b"abcdef") == 5
    assert buffer.get_buffered_audio() == b"abcde"
    assert buffer.is_buffer_full()
    assert not hasattr(buffer, "detect_silence")
    assert not hasattr(buffer, "check_silence_timeout")


def test_audio_buffer_lifecycle_is_storage_only():
    buffer = AudioBuffer("conv", logger=Mock())
    buffer.start_buffering()
    buffer.append(b"frame")
    assert buffer.is_buffering()
    buffer.stop_buffering()
    assert not buffer.is_buffering()
    assert buffer.get_buffered_audio() is None
