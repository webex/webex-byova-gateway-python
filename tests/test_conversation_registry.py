"""Tests for process-wide transport ownership."""

import pytest

from src.core.conversation_registry import (
    ConversationConflictError,
    ConversationRegistry,
    ConversationStore,
)


def test_same_conversation_id_is_isolated_by_customer_org():
    registry = ConversationRegistry()
    first = registry.acquire(
        customer_org_id="org-a",
        conversation_id="call-1",
        transport="grpc",
        agent_id="agent",
        connection_id="grpc-1",
    )
    second = registry.acquire(
        customer_org_id="org-b",
        conversation_id="call-1",
        transport="websocket",
        agent_id="agent",
        connection_id="ws-1",
    )
    assert first.key != second.key


def test_active_conversation_rejects_another_transport():
    registry = ConversationRegistry()
    registry.acquire(
        customer_org_id="org-a",
        conversation_id="call-1",
        transport="grpc",
        agent_id="agent",
        connection_id="grpc-1",
    )
    with pytest.raises(ConversationConflictError):
        registry.acquire(
            customer_org_id="org-a",
            conversation_id="call-1",
            transport="websocket",
            agent_id="agent",
            connection_id="ws-1",
        )


def test_grpc_can_reactivate_inactive_matching_lease():
    registry = ConversationRegistry()
    lease = registry.acquire(
        customer_org_id="org-a",
        conversation_id="call-1",
        transport="grpc",
        agent_id="agent",
        connection_id="grpc-1",
    )
    registry.deactivate(lease)
    replacement = registry.acquire(
        customer_org_id="org-a",
        conversation_id="call-1",
        transport="grpc",
        agent_id="agent",
        connection_id="grpc-2",
        allow_transport_reconnect=True,
    )
    assert replacement.connection_id == "grpc-2"


def test_store_preserves_unambiguous_legacy_string_reads():
    store = ConversationStore[str]()
    store[("org-a", "call-1")] = "processor"
    assert "call-1" in store
    assert store["call-1"] == "processor"
