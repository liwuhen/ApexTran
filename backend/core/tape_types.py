"""Tape value types — project-owned (no longer a republic facade).

Bundles the append-only ``TapeEntry``, the fluent ``TapeQuery`` builder, and the
``TapeContext`` selection rules (plus ``build_messages``) that turn stored entries
into a prompt context. Stores live in ``store.py``; this module is import-light so
``store`` can depend on it without a cycle.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from datetime import date as date_type
from typing import TYPE_CHECKING, Any, Self, TypeVar, overload

from backend.core.errors import AgentError

if TYPE_CHECKING:
    from backend.core.store import AsyncTapeStore, TapeStore


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class TapeEntry:
    """A single append-only entry in a tape."""

    id: int
    kind: str
    payload: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)
    date: str = field(default_factory=utc_now)

    def copy(self) -> TapeEntry:
        return TapeEntry(self.id, self.kind, dict(self.payload), dict(self.meta), self.date)

    @classmethod
    def message(cls, message: dict[str, Any], **meta: Any) -> TapeEntry:
        return cls(id=0, kind="message", payload=dict(message), meta=dict(meta))

    @classmethod
    def system(cls, content: str, **meta: Any) -> TapeEntry:
        return cls(id=0, kind="system", payload={"content": content}, meta=dict(meta))

    @classmethod
    def anchor(cls, name: str, state: dict[str, Any] | None = None, **meta: Any) -> TapeEntry:
        payload: dict[str, Any] = {"name": name}
        if state is not None:
            payload["state"] = dict(state)
        return cls(id=0, kind="anchor", payload=payload, meta=dict(meta))

    @classmethod
    def tool_call(cls, calls: list[dict[str, Any]], **meta: Any) -> TapeEntry:
        return cls(id=0, kind="tool_call", payload={"calls": calls}, meta=dict(meta))

    @classmethod
    def tool_result(cls, results: list[Any], **meta: Any) -> TapeEntry:
        return cls(id=0, kind="tool_result", payload={"results": results}, meta=dict(meta))

    @classmethod
    def error(cls, error: AgentError, **meta: Any) -> TapeEntry:
        return cls(id=0, kind="error", payload=error.as_dict(), meta=dict(meta))

    @classmethod
    def event(cls, name: str, data: dict[str, Any] | None = None, **meta: Any) -> TapeEntry:
        payload: dict[str, Any] = {"name": name}
        if data is not None:
            payload["data"] = dict(data)
        return cls(id=0, kind="event", payload=payload, meta=dict(meta))


T = TypeVar("T", bound="TapeStore | AsyncTapeStore", covariant=True)


@dataclass(frozen=True)
class TapeQuery[T: "TapeStore | AsyncTapeStore"]:
    """Immutable, fluent query over a single tape's entries."""

    tape: str
    store: T
    _query: str | None = None
    _after_anchor: str | None = None
    _after_last: bool = False
    _between_anchors: tuple[str, str] | None = None
    _between_dates: tuple[str, str] | None = None
    _kinds: tuple[str, ...] = field(default_factory=tuple)
    _limit: int | None = None

    def query(self, value: str) -> Self:
        return replace(self, _query=value)

    def after_anchor(self, name: str) -> Self:
        if not name:
            return replace(self, _after_anchor=None, _after_last=False)
        return replace(self, _after_anchor=name, _after_last=False)

    def last_anchor(self) -> Self:
        return replace(self, _after_anchor=None, _after_last=True)

    def between_anchors(self, start: str, end: str) -> Self:
        return replace(self, _between_anchors=(start, end))

    def between_dates(self, start: str | date_type, end: str | date_type) -> Self:
        start_value = start.isoformat() if isinstance(start, date_type) else start
        end_value = end.isoformat() if isinstance(end, date_type) else end
        return replace(self, _between_dates=(start_value, end_value))

    def kinds(self, *kinds: str) -> Self:
        return replace(self, _kinds=kinds)

    def limit(self, value: int) -> Self:
        return replace(self, _limit=value)

    @overload
    def all(self: TapeQuery[TapeStore]) -> Iterable[TapeEntry]: ...

    @overload
    async def all(self: TapeQuery[AsyncTapeStore]) -> Iterable[TapeEntry]: ...

    def all(self) -> Iterable[TapeEntry] | Coroutine[None, None, Iterable[TapeEntry]]:
        return self.store.fetch_all(self)


class _LastAnchor:
    def __repr__(self) -> str:
        return "LAST_ANCHOR"


LAST_ANCHOR = _LastAnchor()
type AnchorSelector = str | None | _LastAnchor
type SelectedMessages = list[dict[str, Any]] | Coroutine[Any, Any, list[dict[str, Any]]]
type ContextSelector = Callable[[Iterable[TapeEntry], "TapeContext"], SelectedMessages]


@dataclass(frozen=True)
class TapeContext:
    """Rules for selecting tape entries into a prompt context.

    anchor: LAST_ANCHOR for the most recent anchor, None for the full tape, or an anchor name.
    select: Optional selector called after anchor slicing that returns messages.
    state: Optional state dictionary to be passed along with the context.
    """

    anchor: AnchorSelector = LAST_ANCHOR
    select: ContextSelector | None = None
    state: dict[str, Any] = field(default_factory=dict)

    def build_query(self, query: TapeQuery) -> TapeQuery:
        if self.anchor is None:
            return query
        if isinstance(self.anchor, _LastAnchor):
            return query.last_anchor()
        return query.after_anchor(self.anchor)


def build_messages(entries: Iterable[TapeEntry], context: TapeContext) -> SelectedMessages:
    if context.select is not None:
        return context.select(entries, context)
    return _default_messages(entries)


def _default_messages(entries: Iterable[TapeEntry]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for entry in entries:
        if entry.kind != "message":
            continue
        payload = entry.payload
        if not isinstance(payload, dict):
            continue
        messages.append(dict(payload))
    return messages


__all__ = [
    "LAST_ANCHOR",
    "AnchorSelector",
    "ContextSelector",
    "SelectedMessages",
    "TapeContext",
    "TapeEntry",
    "TapeQuery",
    "build_messages",
    "utc_now",
]
