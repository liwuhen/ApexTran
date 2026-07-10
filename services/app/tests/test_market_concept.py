"""所属板块 / 行业 enrichment on the akshare hotlist source.

The 股票热榜 "概念" column is each stock's industry board (半导体 vs 医药 …).
These tests stub the blocking akshare call so no network is needed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource
from apextran_app.modules.market.domain.models import HotItem


def _item(symbol: str) -> HotItem:
    return HotItem(rank=1, symbol=symbol, name=symbol, updated_at=datetime.now(UTC))


@pytest.mark.asyncio
async def test_industry_parsed_and_cached() -> None:
    source = AkshareMarketSource()
    calls = 0

    async def fake_records(call: Any) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        return [
            {"item": "股票代码", "value": "688416"},
            {"item": "行业", "value": "半导体"},
            {"item": "总市值", "value": 12345},
        ]

    source._records = fake_records  # type: ignore[method-assign]

    assert await source._industry_for("688416") == "半导体"
    # second lookup is served from the day-long cache — no extra upstream call
    assert await source._industry_for("688416") == "半导体"
    assert calls == 1


@pytest.mark.asyncio
async def test_enrich_is_best_effort_on_failure() -> None:
    source = AkshareMarketSource()

    async def boom(call: Any) -> list[dict[str, Any]]:
        raise RuntimeError("upstream down")

    source._records = boom  # type: ignore[method-assign]

    items = [_item("600519"), _item("000001")]
    # must not raise; concepts simply stay blank
    await source._enrich_concepts(items)
    assert all(item.concept == "" for item in items)
