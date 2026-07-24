from byova_e2e.artifacts import redact_destination


def test_redact_destination_preserves_only_suffix() -> None:
    assert redact_destination("tel:+15551234567") == "***4567"
    assert redact_destination("9999") == "***"
