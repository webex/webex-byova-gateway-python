"""Tests for provider-neutral BYOVA handoff normalization."""

from src.utils.handoff import normalize_handoff


def test_normalize_handoff_keeps_only_canonical_fields():
    handoff = normalize_handoff(
        {
            "summary": "  Caller needs billing help.  ",
            "routing_hint": "  billing_specialist  ",
            "provider_queue_id": "raw-queue-id-98765",
            "provider_diagnostics": {"internal": True},
        }
    )

    assert handoff == {
        "summary": "Caller needs billing help.",
        "routing_hint": "billing_specialist",
    }


def test_normalize_handoff_omits_invalid_optional_fields():
    assert normalize_handoff(
        {"summary": ["not", "text"], "routing_hint": "billing queue"}
    ) == {}
