"""Process-wide conversation ownership shared by gateway transports."""

from __future__ import annotations

import threading
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass
from typing import Generic, Tuple, TypeVar

ConversationKey = Tuple[str, str]
T = TypeVar("T")


class ConversationConflictError(RuntimeError):
    """Raised when another transport or connection owns a conversation."""


@dataclass(frozen=True)
class ConversationLease:
    """A snapshot of the registered owner for a conversation."""

    customer_org_id: str
    conversation_id: str
    transport: str
    agent_id: str
    connection_id: str | None

    @property
    def key(self) -> ConversationKey:
        return (self.customer_org_id, self.conversation_id)


class ConversationRegistry:
    """Coordinate exclusive conversation ownership across transports.

    A gRPC lease may remain registered but inactive between request-stream
    continuations. WebSocket leases are removed when their socket closes.
    """

    def __init__(self) -> None:
        self._leases: dict[ConversationKey, ConversationLease] = {}
        self._lock = threading.RLock()

    @staticmethod
    def key(customer_org_id: str, conversation_id: str) -> ConversationKey:
        return (customer_org_id or "", conversation_id)

    def acquire(
        self,
        *,
        customer_org_id: str,
        conversation_id: str,
        transport: str,
        agent_id: str,
        connection_id: str,
        allow_transport_reconnect: bool = False,
    ) -> ConversationLease:
        """Register and activate a conversation lease.

        ``allow_transport_reconnect`` permits the same transport and agent to
        reactivate an inactive lease. It never permits two active owners.
        """

        key = self.key(customer_org_id, conversation_id)
        with self._lock:
            existing = self._leases.get(key)
            if existing is not None:
                reconnect_allowed = (
                    allow_transport_reconnect
                    and existing.connection_id is None
                    and existing.transport == transport
                    and existing.agent_id == agent_id
                )
                if not reconnect_allowed:
                    raise ConversationConflictError(
                        "conversation is already owned by another connection"
                    )

            lease = ConversationLease(
                customer_org_id=customer_org_id or "",
                conversation_id=conversation_id,
                transport=transport,
                agent_id=agent_id,
                connection_id=connection_id,
            )
            self._leases[key] = lease
            return lease

    def deactivate(self, lease: ConversationLease) -> None:
        """Keep a lease registered while releasing its active connection."""

        with self._lock:
            current = self._leases.get(lease.key)
            if current == lease:
                self._leases[lease.key] = ConversationLease(
                    customer_org_id=lease.customer_org_id,
                    conversation_id=lease.conversation_id,
                    transport=lease.transport,
                    agent_id=lease.agent_id,
                    connection_id=None,
                )

    def release(self, lease: ConversationLease) -> None:
        """Remove a lease only when it still belongs to the caller."""

        with self._lock:
            if self._leases.get(lease.key) == lease:
                del self._leases[lease.key]

    def release_key(self, key: ConversationKey) -> None:
        """Remove a registered conversation after processor cleanup."""

        with self._lock:
            self._leases.pop(key, None)

    def get(self, key: ConversationKey) -> ConversationLease | None:
        with self._lock:
            return self._leases.get(key)

    def snapshot(self) -> dict[ConversationKey, ConversationLease]:
        with self._lock:
            return dict(self._leases)


class ConversationStore(MutableMapping[ConversationKey, T], Generic[T]):
    """Tuple-keyed store with read compatibility for legacy string lookups."""

    def __init__(self) -> None:
        self._values: dict[ConversationKey, T] = {}

    def _resolve(self, key: ConversationKey | str) -> ConversationKey:
        if isinstance(key, tuple):
            return key
        matches = [candidate for candidate in self._values if candidate[1] == key]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise KeyError(key)
        raise KeyError(f"conversation_id {key!r} is ambiguous across organizations")

    def __getitem__(self, key: ConversationKey | str) -> T:
        return self._values[self._resolve(key)]

    def __setitem__(self, key: ConversationKey, value: T) -> None:
        if not isinstance(key, tuple) or len(key) != 2:
            raise TypeError("conversation store keys must be (org_id, conversation_id)")
        self._values[key] = value

    def __delitem__(self, key: ConversationKey | str) -> None:
        del self._values[self._resolve(key)]

    def __iter__(self) -> Iterator[ConversationKey]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __contains__(self, key: object) -> bool:
        try:
            if isinstance(key, (str, tuple)):
                return self._resolve(key) in self._values
        except KeyError:
            pass
        return False
