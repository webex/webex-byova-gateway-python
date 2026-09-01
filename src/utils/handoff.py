"""Provider-neutral validation for optional BYOVA handoff data."""

import re
from collections.abc import Mapping
from typing import Any, Dict, Optional

# Routing hints are stable symbolic classifications, not customer-owned WxCC
# queue identifiers. Keep the wire value simple so the Flow Designer mapping
# remains explicit and the gateway never carries a raw provider queue ID.
_ROUTING_HINT_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


def normalize_routing_hint(value: Any) -> Optional[str]:
    """Return a normalized symbolic routing hint or ``None`` when invalid.

    Hints must be short ASCII identifiers beginning with a letter. This permits
    stable business classifications such as ``billing_specialist`` while
    rejecting empty values, free-form text, and numeric queue identifiers.
    """
    if not isinstance(value, str):
        return None
    routing_hint = value.strip()
    if not _ROUTING_HINT_PATTERN.fullmatch(routing_hint):
        return None
    return routing_hint


def normalize_handoff(value: Any) -> Dict[str, str]:
    """Return the canonical allowlisted handoff shape for any connector.

    A connector extracts provider-specific terminal data, passes a mapping with
    the canonical field names, and receives only valid ``summary`` and
    ``routing_hint`` values. All other provider fields are intentionally
    discarded at this trust boundary.
    """
    if not isinstance(value, Mapping):
        return {}

    handoff: Dict[str, str] = {}
    raw_summary = value.get("summary")
    if isinstance(raw_summary, str):
        summary = raw_summary.strip()
        if summary:
            handoff["summary"] = summary

    routing_hint = normalize_routing_hint(value.get("routing_hint"))
    if routing_hint:
        handoff["routing_hint"] = routing_hint
    return handoff
