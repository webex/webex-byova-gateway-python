"""Tests for provider-neutral BYOVA handoff normalization."""

from collections import UserDict

import pytest

from src.utils.handoff import normalize_handoff, normalize_routing_hint


def test_normalize_handoff_keeps_only_canonical_fields():
    handoff = normalize_handoff(
        UserDict(
            {
                "summary": "  Caller needs billing help.  ",
                "routing_hint": "  billing_specialist  ",
                "provider_queue_id": "raw-queue-id-98765",
                "provider_diagnostics": {"internal": True},
            }
        )
    )

    assert handoff == {
        "summary": "Caller needs billing help.",
        "routing_hint": "billing_specialist",
    }


def test_normalize_handoff_omits_invalid_optional_fields():
    assert (
        normalize_handoff({"summary": ["not", "text"], "routing_hint": "billing queue"})
        == {}
    )


@pytest.mark.parametrize("value", ["A", "billing_specialist", "Delivery-42", "a" * 64])
def test_normalize_routing_hint_accepts_symbolic_identifiers(value):
    assert normalize_routing_hint(f"  {value}  ") == value


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "  ",
        True,
        123,
        "123",
        "billing queue",
        "a" * 65,
        "café",
        "queue/name",
        "billing\nqueue",
        "billing\x00queue",
    ],
)
def test_invalid_routing_hint_preserves_summary(value):
    assert normalize_handoff(
        {"summary": "Caller needs help.", "routing_hint": value}
    ) == {"summary": "Caller needs help."}


@pytest.mark.parametrize("value", [None, "summary", ["summary"], True])
def test_normalize_handoff_ignores_non_mappings(value):
    assert normalize_handoff(value) == {}
