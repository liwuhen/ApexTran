"""Quote metric normalization and propagation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from apextran_app.modules.market.adapters.akshare_source import (
    _build_stock_search_results,
    _stock_search_item_from_tencent_quote,
)
from apextran_app.modules.market.adapters.mock_source import MockMarketSource
from apextran_app.modules.market.domain.models import StockSearchItem
from apextran_app.modules.market.service import _quote_from_stock, _quote_has_data


def test_akshare_spot_metrics_keep_normalized_units() -> None:
    item = _build_stock_search_results(
        [
            {
                "代码": "600519",
                "名称": "贵州茅台",
                "最新价": 1418.01,
                "涨跌幅": 0.56,
                "换手率": 0.19,
                "成交额": 2_818_724_096.0,
                "流通市值": 1_781_300_000_000.0,
                "总市值": 1_781_300_000_000.0,
            }
        ],
        "600519",
        1,
    )[0]

    assert item.turnover_rate == 0.19
    assert item.amount == 2_818_724_096.0
    assert item.float_market_cap == 1_781_300_000_000.0
    assert item.total_market_cap == 1_781_300_000_000.0


def test_tencent_quote_prefers_exact_amount_and_scales_market_caps_to_yuan() -> None:
    parts = _tencent_parts()
    parts[35] = "1418.01/19879/2818724096.00"
    parts[37] = "281872.41"

    item = _stock_search_item_from_tencent_quote("600519", "~".join(parts))

    assert item is not None
    assert item.turnover_rate == 0.19
    assert item.amount == 2_818_724_096.0
    assert item.float_market_cap == 1_781_300_000_000.0
    assert item.total_market_cap == 1_781_300_000_000.0


def test_tencent_quote_falls_back_to_ten_thousand_yuan_amount() -> None:
    parts = _tencent_parts()
    parts[35] = "1418.01/19879"
    parts[37] = "281872.41"

    item = _stock_search_item_from_tencent_quote("600519", "~".join(parts))

    assert item is not None
    assert item.amount == 2_818_724_100.0


def test_quote_conversion_propagates_all_metrics() -> None:
    stock = StockSearchItem(
        symbol="600519",
        name="贵州茅台",
        market="沪市A股",
        latest_price=1418.01,
        change_pct=0.56,
        turnover_rate=0.19,
        amount=2_818_724_096.0,
        float_market_cap=1_781_300_000_000.0,
        total_market_cap=1_781_300_000_000.0,
        source="东方财富",
        updated_at=datetime(2026, 7, 11, tzinfo=UTC),
    )

    quote = _quote_from_stock(stock)

    assert quote.turnover_rate == stock.turnover_rate
    assert quote.amount == stock.amount
    assert quote.float_market_cap == stock.float_market_cap
    assert quote.total_market_cap == stock.total_market_cap
    assert _quote_has_data(quote)


@pytest.mark.asyncio
async def test_mock_stock_search_supplies_quote_metrics() -> None:
    item = (await MockMarketSource().search_stocks("600519", 1))[0]

    assert item.turnover_rate is not None
    assert item.amount is not None
    assert item.float_market_cap is not None
    assert item.total_market_cap is not None
    assert item.total_market_cap >= item.float_market_cap


def _tencent_parts() -> list[str]:
    parts = [""] * 46
    parts[1] = "贵州茅台"
    parts[2] = "600519"
    parts[3] = "1418.01"
    parts[32] = "0.56"
    parts[38] = "0.19"
    parts[44] = "17813.00"
    parts[45] = "17813.00"
    return parts
