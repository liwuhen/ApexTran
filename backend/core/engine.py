"""Tape-storage engine — project-owned (no longer a republic facade).

``ModelEngine`` owns per-tape append-only storage and the default selection
context; ``Tape`` is the per-tape async view returned by :meth:`ModelEngine.tape`.

Model calls do **not** run here — they run through LangGraph in ``llm/graph.py``.
This engine only persists and replays tape entries (messages, anchors, events):
the storage subset ``read_messages_async`` / ``append_async`` / ``query_async`` /
``handoff_async`` / ``reset_async``.
"""

from __future__ import annotations

import inspect
from typing import Any, cast

from backend.core.store import (
    AsyncTapeStore,
    AsyncTapeStoreAdapter,
    TapeStore,
    is_async_tape_store,
)
from backend.core.tape_types import TapeContext, TapeEntry, TapeQuery, build_messages


class Tape:
    """A scoped, async view over a single tape's append-only storage."""

    def __init__(self, name: str, *, store: AsyncTapeStore, default_context: TapeContext) -> None:
        self._name = name
        self._store = store
        self._default_context = default_context
        self._local_context: TapeContext | None = None

    def __repr__(self) -> str:
        return f"<Tape name={self._name}>"

    @property
    def name(self) -> str:
        return self._name

    @property
    def context(self) -> TapeContext:
        return self._local_context or self._default_context

    @context.setter
    def context(self, value: TapeContext | None) -> None:
        self._local_context = value

    @property
    def query_async(self) -> TapeQuery[AsyncTapeStore]:
        return TapeQuery(tape=self._name, store=self._store)

    async def read_messages_async(self, *, context: TapeContext | None = None) -> list[dict[str, Any]]:
        active_context = context or self.context
        query = active_context.build_query(self.query_async)
        entries = await self._store.fetch_all(query)
        messages = build_messages(entries, active_context)
        if inspect.isawaitable(messages):
            messages = await messages
        return messages

    async def append_async(self, entry: TapeEntry) -> None:
        await self._store.append(self._name, entry)

    async def reset_async(self) -> None:
        await self._store.reset(self._name)

    async def handoff_async(
        self,
        name: str,
        *,
        state: dict[str, Any] | None = None,
        **meta: Any,
    ) -> list[TapeEntry]:
        anchor = TapeEntry.anchor(name, state=state, **meta)
        event = TapeEntry.event("handoff", {"name": name, "state": state or {}}, **meta)
        await self._store.append(self._name, anchor)
        await self._store.append(self._name, event)
        return [anchor, event]


class ModelEngine:
    """Append-only tape storage + default context (model calls live in LangGraph)."""

    def __init__(
        self,
        tape_store: TapeStore | AsyncTapeStore,
        context: TapeContext | None = None,
    ) -> None:
        if is_async_tape_store(tape_store):
            self._store: AsyncTapeStore = tape_store
        else:
            self._store = AsyncTapeStoreAdapter(cast("TapeStore", tape_store))
        self._context = context or TapeContext()

    @property
    def context(self) -> TapeContext:
        return self._context

    @context.setter
    def context(self, value: TapeContext) -> None:
        self._context = value

    def tape(self, name: str, *, context: TapeContext | None = None) -> Tape:
        return Tape(name, store=self._store, default_context=context or self._context)


__all__ = ["ModelEngine", "Tape"]
