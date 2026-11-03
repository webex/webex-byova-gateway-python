"""Transport capability tests for the shared virtual-agent router."""

from unittest.mock import MagicMock

import pytest

from src.core.virtual_agent_router import VirtualAgentRouter


def _router() -> VirtualAgentRouter:
    router = VirtualAgentRouter()
    grpc_connector = object()
    websocket_connector = object()
    router.agent_to_connector_map = {
        "Lex Agent": grpc_connector,
        "GECX Agent": websocket_connector,
    }
    router.agent_supported_transports = {
        "Lex Agent": frozenset({"grpc"}),
        "GECX Agent": frozenset({"grpc", "websocket"}),
    }
    return router


def test_agent_discovery_filters_by_transport_without_changing_all_agents_view():
    router = _router()

    assert router.get_all_available_agents() == ["Lex Agent", "GECX Agent"]
    assert router.get_all_available_agents(transport="grpc") == [
        "Lex Agent",
        "GECX Agent",
    ]
    assert router.get_all_available_agents(transport="websocket") == ["GECX Agent"]


def test_runtime_lookup_enforces_same_transport_capability_as_discovery():
    router = _router()

    assert router.get_connector_for_agent("GECX Agent", transport="websocket")
    with pytest.raises(ValueError, match="does not support transport 'websocket'"):
        router.get_connector_for_agent("Lex Agent", transport="websocket")


@pytest.mark.parametrize(
    "value",
    ["websocket", [], ["grpc", "unsupported"]],
)
def test_invalid_connector_transport_declarations_are_rejected(value):
    router = VirtualAgentRouter()

    with pytest.raises(ValueError, match="supported_transports"):
        router._normalize_transports(value, connector_id="test")


def test_dtmf_input_config_is_validated_and_returned():
    router = VirtualAgentRouter()
    connector = MagicMock()
    connector.get_dtmf_input_config.return_value = {
        "dtmf_input_length": 9,
        "inter_digit_timeout_msec": 5000,
        "termchar": "DTMF_DIGIT_POUND",
    }
    router.agent_to_connector_map = {"Menu": connector}
    router.agent_supported_transports = {"Menu": frozenset({"websocket"})}

    assert router.get_dtmf_input_config("Menu", "websocket") == {
        "dtmf_input_length": 9,
        "inter_digit_timeout_msec": 5000,
        "termchar": "DTMF_DIGIT_POUND",
    }


@pytest.mark.parametrize(
    "config",
    [
        {"dtmf_input_length": 0, "inter_digit_timeout_msec": 5000,
         "termchar": "DTMF_DIGIT_POUND"},
        {"dtmf_input_length": 9, "inter_digit_timeout_msec": 0,
         "termchar": "DTMF_DIGIT_POUND"},
        {"dtmf_input_length": 9, "inter_digit_timeout_msec": 5000,
         "termchar": "NOT_A_DIGIT"},
    ],
)
def test_invalid_dtmf_input_config_is_rejected(config):
    router = VirtualAgentRouter()
    connector = MagicMock()
    connector.get_dtmf_input_config.return_value = config
    router.agent_to_connector_map = {"Menu": connector}
    router.agent_supported_transports = {"Menu": frozenset({"websocket"})}

    with pytest.raises(ValueError, match="DTMF"):
        router.get_dtmf_input_config("Menu", "websocket")
