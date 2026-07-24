"""LiveMarketSource merge logic — 同花顺 + 东方财富 + 腾讯 into one hotlist.

Pure/monkeypatched: no network. Verifies rank joining, concept passthrough, and
that an Eastmoney-only symbol still lands with a name from the Tencent quote.
"""

from __future__ import annotations

import pytest
from apextran_app.modules.market.adapters.live_source import LiveMarketSource, _parse_boards


@pytest.mark.parametrize(
    ("tag", "expected"),
    [("4天3板", 3), ("5天3板", 3), ("2连板", 2), ("首板涨停", 1), ("首板", 1), ("持续上榜", 0), ("", 0)],
)
def test_parse_boards(tag: str, expected: int) -> None:
    assert _parse_boards(tag) == expected


def test_merge_joins_ranks_and_concept() -> None:
    source = LiveMarketSource()
    ths = {
        "301308": {"name": "江波龙", "change_pct": 3.14, "concept": "存储芯片", "ths_rank": 1, "popularity": "持续上榜"},
    }
    em = {"301308": {"em_rank": 1}, "600000": {"em_rank": 2}}
    quotes = {
        "301308": {"name": "江波龙", "price": 618.0, "change_pct": 3.14},
        "600000": {"name": "浦发银行", "price": 10.0, "change_pct": 1.2},
    }

    items = source._merge(ths, em, quotes)
    by_symbol = {it.symbol: it for it in items}

    top = by_symbol["301308"]
    assert top.eastmoney_rank == 1
    assert top.tonghuashun_rank == 1
    assert top.concept == "存储芯片"
    assert top.change_pct == 3.14
    assert set(top.sources) == {"东方财富", "同花顺"}

    # Eastmoney-only symbol: no 同花顺 rank, name filled from the Tencent quote.
    em_only = by_symbol["600000"]
    assert em_only.eastmoney_rank == 2
    assert em_only.tonghuashun_rank is None
    assert em_only.name == "浦发银行"
    assert em_only.sources == ["东方财富"]


@pytest.mark.asyncio
async def test_fetch_hotlist_wires_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    source = LiveMarketSource()

    async def fake_ths(_client: object) -> dict[str, dict[str, object]]:
        return {"301308": {"name": "江波龙", "change_pct": 3.14, "concept": "存储芯片", "ths_rank": 1, "popularity": ""}}

    async def fake_em(_client: object) -> dict[str, dict[str, object]]:
        return {"301308": {"em_rank": 1}}

    async def fake_quotes(_client: object, _codes: list[str]) -> dict[str, dict[str, object]]:
        return {"301308": {"name": "江波龙", "price": 618.0, "change_pct": 3.14}}

    monkeypatch.setattr(source, "_ths_hot", fake_ths)
    monkeypatch.setattr(source, "_em_hot", fake_em)
    monkeypatch.setattr(source, "_tencent_quotes", fake_quotes)

    items = await source.fetch_hotlist()
    assert len(items) == 1
    assert items[0].symbol == "301308"
    assert items[0].concept == "存储芯片"
    assert items[0].rank == 1


@pytest.mark.asyncio
async def test_fetch_hotlist_rejects_partial_ranking_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    source = LiveMarketSource()

    async def failed_ths(_client: object) -> None:
        return None

    async def healthy_em(_client: object) -> dict[str, dict[str, object]]:
        return {"301308": {"em_rank": 1}}

    monkeypatch.setattr(source, "_ths_hot", failed_ths)
    monkeypatch.setattr(source, "_em_hot", healthy_em)

    with pytest.raises(RuntimeError, match="incomplete snapshot"):
        await source.fetch_hotlist()
