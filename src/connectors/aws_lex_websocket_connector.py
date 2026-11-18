"""WxCC WebSocket adapter for the shared, utterance-buffered Lex provider."""

from typing import Any

from .aws_lex_connector import AWSLexConnector


class AWSLexWebSocketConnector(AWSLexConnector):
    """Accept WxCC JSON over WebSocket and call Lex using RecognizeUtterance.

    Provider authentication, audio conversion and session handling are shared
    with the gRPC adapter. This does not implement Lex StartConversation.
    """

    agent_id_prefix = "aws_lex_websocket_connector"

    def get_supported_transports(self) -> frozenset[str]:
        """Advertise this adapter only on the WxCC WebSocket listener."""
        return frozenset({"websocket"})

    def get_dtmf_input_config(self, transport: str) -> dict[str, Any]:
        """Keep Lex's ten-digit collection policy on every WebSocket response."""
        del transport
        return {
            "dtmf_input_length": 10,
            "inter_digit_timeout_msec": 5000,
            "termchar": "DTMF_DIGIT_POUND",
        }
