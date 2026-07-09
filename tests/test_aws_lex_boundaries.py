import pytest
from unittest.mock import MagicMock, patch

from src.connectors.aws_lex_connector import AWSLexConnector


@pytest.fixture
def connector():
    with patch("boto3.Session") as session_class:
        session = MagicMock()
        session.client.side_effect = lambda service: MagicMock()
        session_class.return_value = session
        return AWSLexConnector({"region_name": "us-east-1", "barge_in_enabled": False})


def test_lex_appends_each_frame_and_flushes_only_on_central_end(connector):
    connector.session_manager.has_session = MagicMock(return_value=True)
    connector.session_manager.get_session_id = MagicMock(return_value="session")
    connector.session_manager.get_bot_id = MagicMock(return_value="bot")
    connector.session_manager.get_bot_name = MagicMock(return_value="bot")
    with patch.object(connector.audio_processor, "append_audio_frame") as append:
        assert list(connector.send_message("conv", {"input_type": "audio", "audio_data": b"frame"})) == [None]
    append.assert_called_once_with(b"frame", "conv")
    with patch.object(connector, "_send_audio_to_lex", return_value=iter([{"message_type": "response"}])) as flush:
        assert list(connector.send_message("conv", {"input_type": "speech_boundary", "speech_boundary": {"kind": "speech_ended"}})) == [{"message_type": "response"}]
    flush.assert_called_once_with("conv")
