"""Bounded byte storage for connector-owned audio utterances."""

import logging
from typing import Any, Dict, Optional


class AudioBuffer:
    """Store audio bytes; speech boundary detection belongs to the gateway VAD."""

    def __init__(
        self, conversation_id: str, max_buffer_size: int = 1024 * 1024,
        logger: Optional[logging.Logger] = None, **_ignored: Any,
    ) -> None:
        self.conversation_id = conversation_id
        self.max_buffer_size = max_buffer_size
        self.sample_rate = _ignored.get("sample_rate", 8000)
        self.bit_depth = _ignored.get("bit_depth", 8)
        self.channels = _ignored.get("channels", 1)
        self.encoding = _ignored.get("encoding", "ulaw")
        self.logger = logger or logging.getLogger(__name__)
        self.audio_buffer = bytearray()
        self.buffering = False

    def start_buffering(self) -> None:
        self.clear_buffer()
        self.buffering = True

    def append(self, audio_data: bytes) -> int:
        if not audio_data:
            return 0
        accepted = audio_data[:max(0, self.max_buffer_size - len(self.audio_buffer))]
        self.audio_buffer.extend(accepted)
        if len(accepted) < len(audio_data):
            self.logger.warning("Audio buffer limit reached for %s", self.conversation_id)
        return len(accepted)

    def add_audio_data(self, audio_data: bytes, encoding: str = "ulaw") -> int:
        """Compatibility alias for callers that only need byte storage."""
        del encoding
        return self.append(audio_data)

    def get_buffered_audio(self) -> Optional[bytes]:
        return bytes(self.audio_buffer) if self.audio_buffer else None

    def get_buffer_size(self) -> int:
        return len(self.audio_buffer)

    def is_buffer_full(self) -> bool:
        return len(self.audio_buffer) >= self.max_buffer_size

    def clear_buffer(self) -> None:
        self.audio_buffer.clear()

    def reset_buffer(self) -> None:
        self.clear_buffer()
        self.buffering = False

    def stop_buffering(self) -> None:
        self.reset_buffer()

    def is_buffering(self) -> bool:
        return self.buffering

    def get_buffering_stats(self) -> Dict[str, Any]:
        buffer_size = len(self.audio_buffer)
        return {
            "conversation_id": self.conversation_id,
            "is_buffering": self.buffering,
            "buffer_size": buffer_size,
            "max_buffer_size": self.max_buffer_size,
            "buffer_utilization": (
                buffer_size / self.max_buffer_size * 100
                if self.max_buffer_size
                else 0
            ),
        }
