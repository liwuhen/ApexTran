"""M1 smoke tests — the chain runs end to end on the mock source."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from uuid import uuid4

from apextran_app.config import get_settings
from apextran_app.main import create_app
from fastapi.testclient import TestClient

_TEST_INTERNAL_JWT_SECRET = "test-internal-jwt-secret"  # noqa: S105

os.environ["APP_ENVIRONMENT"] = "dev"
os.environ["APP_CACHE_BACKEND"] = "memory"
os.environ["APP_DB_URL"] = ""
os.environ["APP_MARKET_SOURCE"] = "mock"
os.environ["APP_INTERNAL_JWT_SECRET"] = _TEST_INTERNAL_JWT_SECRET
get_settings.cache_clear()

client = TestClient(create_app())


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _internal_jwt(
    sub: str,
    *,
    aud: str = "apextran-app",
    scopes: list[str] | None = None,
    secret: str = _TEST_INTERNAL_JWT_SECRET,
    exp_delta: int = 300,
) -> str:
    header = {"alg": "HS256", "typ": "JWT", "kid": "test"}
    now = int(time.time())
    payload = {
        "iss": "apextran-bff",
        "aud": aud,
        "sub": sub,
        "scope": scopes or ["market:read", "market:watchlists:read", "market:watchlists:write"],
        "iat": now,
        "exp": now + exp_delta,
        "jti": str(uuid4()),
    }
    signing_input = ".".join(
        [
            _b64url(json.dumps(header).encode()),
            _b64url(json.dumps(payload).encode()),
        ]
    )
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _auth_headers(user_id: str = "user-a", scopes: list[str] | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {_internal_jwt(user_id, scopes=scopes)}"}


def test_healthz() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_hotlist_returns_items() -> None:
    resp = client.get("/api/v1/market/hotlist")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) > 0
    assert {
        "rank",
        "symbol",
        "name",
        "boards",
        "concept",
        "hot_score",
        "eastmoney_rank",
        "tonghuashun_rank",
        "sources",
        "updated_at",
    } <= body[0].keys()
    # mock source labels each sample with its sector board (股票热榜 "概念" column)
    assert any(item["concept"] for item in body)
    # public data must be CDN-cacheable
    assert "s-maxage" in resp.headers.get("cache-control", "")


def test_stock_search_by_code_or_name() -> None:
    by_code = client.get("/api/v1/market/stocks/search", params={"q": "600519"})
    assert by_code.status_code == 200
    code_body = by_code.json()
    assert code_body
    assert code_body[0]["symbol"] == "600519"
    assert code_body[0]["name"] == "贵州茅台"
    assert {"symbol", "name", "market", "latest_price", "change_pct", "updated_at"} <= code_body[0].keys()
    assert "s-maxage" in by_code.headers.get("cache-control", "")

    by_name = client.get("/api/v1/market/stocks/search", params={"q": "贵州"})
    assert by_name.status_code == 200
    assert any(item["symbol"] == "600519" for item in by_name.json())


def test_headlines_filter_by_symbol() -> None:
    resp = client.get("/api/v1/market/headlines", params={"symbol": "600519"})
    assert resp.status_code == 200
    body = resp.json()
    assert body and all("600519" in item["symbols"] for item in body)


def test_flash_and_news() -> None:
    assert client.get("/api/v1/market/flash").status_code == 200
    news_resp = client.get("/api/v1/market/news", params={"category": "科技"})
    assert news_resp.status_code == 200
    body = news_resp.json()
    if body:
        assert any(item["source"] == "财联社" for item in body)
        assert any(item["source"] == "东方财富" for item in body)
        assert any(item["source"] == "同花顺" for item in body)
        assert any(item["source"] == "第一财经" for item in body)
        assert any(item["source"] == "雪球" for item in body)


def test_ai_hotspots_endpoint_returns_ranked_items() -> None:
    resp = client.get("/api/v1/market/ai-hotspots")
    assert resp.status_code == 200
    body = resp.json()
    assert body
    assert {"id", "title", "summary", "source", "url", "tags", "heat"} <= body[0].keys()
    assert body[0]["source"] == "AI智能热榜"
    assert "财经热点" in body[0]["tags"]


def test_openapi_exposes_market_contract() -> None:
    spec = client.get("/openapi.json").json()
    assert "/api/v1/market/hotlist" in spec["paths"]
    assert "/api/v1/market/stocks/search" in spec["paths"]
    assert "/api/v1/market/quotes" in spec["paths"]
    assert "/api/v1/market/ai-hotspots" in spec["paths"]
    assert "/api/v1/market/klines/{symbol}" in spec["paths"]
    assert "/api/v1/market/intraday/{symbol}" in spec["paths"]
    assert "/api/v1/market/watchlists" in spec["paths"]
    assert "/api/v1/market/watchlists/default/items" in spec["paths"]


def test_daily_klines_endpoint_returns_ordered_candles() -> None:
    resp = client.get("/api/v1/market/klines/600519", params={"limit": 30})
    assert resp.status_code == 200
    bars = resp.json()
    assert len(bars) == 30
    assert {"date", "open", "high", "low", "close", "volume"} <= bars[0].keys()
    assert [bar["date"] for bar in bars] == sorted(bar["date"] for bar in bars)  # oldest-first
    assert all(bar["low"] <= min(bar["open"], bar["close"]) for bar in bars)
    assert all(bar["high"] >= max(bar["open"], bar["close"]) for bar in bars)
    assert "s-maxage" in resp.headers.get("cache-control", "")


def test_intraday_endpoint_returns_one_full_session() -> None:
    resp = client.get("/api/v1/market/intraday/600519")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "600519"
    assert body["prev_close"] is not None
    # 09:30–11:30 plus 13:00–15:00, both endpoints inclusive.
    assert len(body["points"]) == 242
    assert body["points"][0]["time"] == "09:30"
    assert body["points"][-1]["time"] == "15:00"
    assert "s-maxage" in resp.headers.get("cache-control", "")


def test_chart_endpoints_reject_non_a_share_symbols() -> None:
    assert client.get("/api/v1/market/klines/AAPL").status_code == 422
    assert client.get("/api/v1/market/intraday/60051").status_code == 422


def test_tencent_kline_row_maps_open_close_high_low_in_source_order() -> None:
    """腾讯 orders a day row [date, open, close, high, low, volume] — not OHLC."""
    from apextran_app.modules.market.adapters.live_source import _kline_bar

    bar = _kline_bar(["2026-07-07", "1200.000", "1188.800", "1202.000", "1188.110", "27365.000"])

    assert bar is not None
    assert (bar.open, bar.close, bar.high, bar.low) == (1200.0, 1188.8, 1202.0, 1188.11)
    assert bar.volume == 27365.0
    assert _kline_bar(["2026-07-07", "1200.000"]) is None
    assert _kline_bar(["2026-07-07", "", "1188.800", "1202.000", "1188.110", "1"]) is None


def test_tencent_intraday_drops_after_hours_ticks_and_derives_vwap() -> None:
    """深交所 盘后定价 runs to 15:30; those ticks must not enter the 分时 curve."""
    from apextran_app.modules.market.adapters.live_source import _intraday_points

    points = _intraday_points([
        "0930 10.50 5697 5981850.00",
        "0931 10.40 0 0.00",
        "1500 10.45 957946 1000372053.82",
        "1530 10.45 957958 1000384593.82",
    ])

    assert [point.time for point in points] == ["09:30", "09:31", "15:00"]
    # 5981850 / (5697 手 × 100 shares) = 10.5000...
    assert points[0].avg_price == 10.5
    assert points[1].avg_price is None  # no turnover yet → no VWAP
    assert points[2].avg_price == 10.443


def test_tencent_intraday_date_is_normalized_to_iso() -> None:
    from apextran_app.modules.market.adapters.live_source import _iso_date

    assert _iso_date("20260710") == "2026-07-10"
    assert _iso_date("") == ""


def test_quotes_endpoint_returns_short_lived_public_quotes() -> None:
    resp = client.get("/api/v1/market/quotes", params={"symbols": "沪市A股:600519,深市A股:300750"})
    assert resp.status_code == 200
    body = resp.json()
    assert [item["symbol"] for item in body] == ["600519", "300750"]
    assert {"symbol", "market", "latest_price", "change_pct", "source", "updated_at"} <= body[0].keys()
    assert "s-maxage" in resp.headers.get("cache-control", "")


def test_private_watchlist_requires_internal_jwt() -> None:
    resp = client.get("/api/v1/market/watchlists/default/items")
    assert resp.status_code == 401


def test_private_watchlist_rejects_bad_jwt_signature() -> None:
    token = _internal_jwt("user-a")
    prefix, signature = token.rsplit(".", 1)
    bad_signature = f"{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
    resp = client.get(
        "/api/v1/market/watchlists/default/items",
        headers={"Authorization": f"Bearer {prefix}.{bad_signature}"},
    )
    assert resp.status_code == 401


def test_private_watchlist_rejects_wrong_audience() -> None:
    resp = client.get(
        "/api/v1/market/watchlists/default/items",
        headers={"Authorization": f"Bearer {_internal_jwt('user-a', aud='market')}"},
    )
    assert resp.status_code == 401


def test_private_watchlist_write_requires_scope() -> None:
    resp = client.post(
        "/api/v1/market/watchlists/default/items",
        headers=_auth_headers(scopes=["market:read", "market:watchlists:read"]),
        json={
            "symbol": "600519",
            "name": "贵州茅台",
            "market": "沪市A股",
            "updated_at": "2026-07-08T12:00:00Z",
        },
    )
    assert resp.status_code == 403


def test_private_watchlist_isolated_by_jwt_subject() -> None:
    create_resp = client.post(
        "/api/v1/market/watchlists/default/items",
        headers=_auth_headers("market-user-a"),
        json={
            "symbol": "600519",
            "name": "贵州茅台",
            "market": "沪市A股",
            "latest_price": 1199.3,
            "change_pct": 0.88,
            "concept": "白酒",
            "source": "mock",
            "updated_at": "2026-07-08T12:00:00Z",
        },
    )
    assert create_resp.status_code == 201
    assert create_resp.headers["cache-control"] == "no-store"

    user_a_resp = client.get("/api/v1/market/watchlists/default/items", headers=_auth_headers("market-user-a"))
    user_b_resp = client.get("/api/v1/market/watchlists/default/items", headers=_auth_headers("market-user-b"))

    assert [item["instrument"]["symbol"] for item in user_a_resp.json()] == ["600519"]
    assert user_b_resp.json() == []

    delete_resp = client.delete(
        "/api/v1/market/watchlists/default/items/600519?market=沪市A股",
        headers=_auth_headers("market-user-a"),
    )
    assert delete_resp.status_code == 204
    assert client.get("/api/v1/market/watchlists/default/items", headers=_auth_headers("market-user-a")).json() == []


def test_default_watchlist_items_optionally_include_quotes() -> None:
    create_resp = client.post(
        "/api/v1/market/watchlists/default/items",
        headers=_auth_headers("market-quote-user"),
        json={
            "symbol": "600519",
            "name": "贵州茅台",
            "market": "沪市A股",
            "updated_at": "2026-07-08T12:00:00Z",
        },
    )
    assert create_resp.status_code == 201

    plain_resp = client.get(
        "/api/v1/market/watchlists/default/items",
        headers=_auth_headers("market-quote-user"),
    )
    assert plain_resp.status_code == 200
    assert "quote" not in plain_resp.json()[0]

    quoted_resp = client.get(
        "/api/v1/market/watchlists/default/items",
        params={"include_quotes": "true"},
        headers=_auth_headers("market-quote-user"),
    )
    assert quoted_resp.status_code == 200
    body = quoted_resp.json()
    assert body[0]["instrument"]["symbol"] == "600519"
    assert body[0]["quote"]["symbol"] == "600519"
    assert body[0]["quote"]["market"] == "沪市A股"


def test_private_watchlist_crud_and_ordering() -> None:
    create_resp = client.post(
        "/api/v1/market/watchlists",
        headers=_auth_headers("market-crud-user"),
        json={"name": "long-term", "sort_order": 2},
    )
    assert create_resp.status_code == 201
    watchlist_id = create_resp.json()["id"]

    patch_resp = client.patch(
        f"/api/v1/market/watchlists/{watchlist_id}",
        headers=_auth_headers("market-crud-user"),
        json={"name": "observe", "sort_order": 1},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "observe"

    for symbol in ("600519", "300750"):
        add_resp = client.post(
            f"/api/v1/market/watchlists/{watchlist_id}/items",
            headers=_auth_headers("market-crud-user"),
            json={
                "symbol": symbol,
                "name": f"stock-{symbol}",
                "market": "沪市A股" if symbol.startswith("6") else "深市A股",
                "latest_price": 1199.3,
                "change_pct": 0.88,
                "source": "test",
                "updated_at": "2026-07-08T12:00:00Z",
            },
        )
        assert add_resp.status_code == 201
        assert add_resp.json()["instrument"]["latest_price"] is None
        assert add_resp.json()["instrument"]["change_pct"] is None

    order_resp = client.patch(
        f"/api/v1/market/watchlists/{watchlist_id}/items/order",
        headers=_auth_headers("market-crud-user"),
        json={
            "items": [
                {"market": "深市A股", "symbol": "300750", "sort_order": 0},
                {"market": "沪市A股", "symbol": "600519", "sort_order": 1},
            ]
        },
    )
    assert order_resp.status_code == 200
    assert [item["instrument"]["symbol"] for item in order_resp.json()] == ["300750", "600519"]

    other_user_resp = client.get(f"/api/v1/market/watchlists/{watchlist_id}/items", headers=_auth_headers("other-user"))
    assert other_user_resp.status_code == 200
    assert other_user_resp.json() == []

    delete_resp = client.delete(
        f"/api/v1/market/watchlists/{watchlist_id}",
        headers=_auth_headers("market-crud-user"),
    )
    assert delete_resp.status_code == 204


def test_finance_hotspots_merge_quicktiny_style_sources() -> None:
    from apextran_app.modules.market.adapters.akshare_source import _build_finance_hotspots

    items = _build_finance_hotspots([
        (
            "eastmoney",
            "东方财富",
            [
                {
                    "标题": "芯片股再度走强",
                    "摘要": "半导体芯片股集体走强",
                    "来源": "东方财富",
                    "链接": "https://finance.eastmoney.com/a.html",
                    "热度": "12.3万",
                    "标签": ["芯片"],
                }
            ],
            False,
        ),
        (
            "ths",
            "同花顺",
            [
                {
                    "标题": "芯片股再度走强，反弹or反转？",
                    "摘要": "中芯国际、寒武纪等领涨",
                    "来源": "同花顺",
                    "链接": "https://news.10jqka.com.cn/a.html",
                    "热度": 535152,
                }
            ],
            False,
        ),
        (
            "baidu",
            "百度",
            [
                {
                    "标题": "超强台风即将进入警戒线",
                    "摘要": "风雨影响逐渐逼近",
                    "来源": "百度",
                    "链接": "https://www.baidu.com/s?wd=weather",
                    "热度": "780.9万",
                },
                {
                    "标题": "从四个新数据读懂上半年中国经济",
                    "摘要": "中国经济高质量发展扎实推进",
                    "来源": "百度",
                    "链接": "https://www.baidu.com/s?wd=economy",
                    "热度": "761.8万",
                },
            ],
            True,
        ),
    ])

    titles = [item.title for item in items]
    assert len([title for title in titles if "芯片股再度走强" in title]) == 1
    assert "从四个新数据读懂上半年中国经济" in titles
    assert "超强台风即将进入警戒线" not in titles
    assert items[0].source == "AI智能热榜"
    assert "东方财富" in items[0].tags
    assert "同花顺" in items[0].tags


def test_news_skips_cls_items_when_cls_feed_unavailable() -> None:
    from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource

    source = AkshareMarketSource()

    async def fake_fetch_cls_rows() -> list[dict[str, object]]:
        raise RuntimeError("feed unavailable")

    async def fake_fetch_eastmoney_rows() -> list[dict[str, object]]:
        return [
            {
                "标题": "东方财富快讯",
                "摘要": "东方财富摘要",
                "内容": "东方财富摘要",
                "来源": "东方财富",
                "链接": "https://kuaixun.eastmoney.com/7_24.html",
                "发布时间": "2026-07-05T10:00:00+00:00",
            }
        ]

    async def fake_fetch_tonghuashun_rows() -> list[dict[str, object]]:
        return [
            {
                "标题": "同花顺快讯",
                "摘要": "同花顺摘要",
                "内容": "同花顺摘要",
                "来源": "同花顺",
                "链接": "https://news.10jqka.com.cn/realtimenews.html",
                "发布时间": "2026-07-05T09:00:00+00:00",
            }
        ]

    async def fake_fetch_yicai_rows() -> list[dict[str, object]]:
        return [
            {
                "标题": "第一财经热榜",
                "摘要": "第一财经摘要",
                "内容": "第一财经摘要",
                "来源": "第一财经",
                "链接": "https://www.yicai.com/news/103208655.html",
                "发布时间": "2026-07-05T08:00:00+00:00",
                "热度": "10热度",
            }
        ]

    async def fake_fetch_xueqiu_rows() -> list[dict[str, object]]:
        return []

    source._fetch_cls_telegraph_rows = fake_fetch_cls_rows  # type: ignore[method-assign]
    source._fetch_eastmoney_news_rows = fake_fetch_eastmoney_rows  # type: ignore[method-assign]
    source._fetch_tonghuashun_news_rows = fake_fetch_tonghuashun_rows  # type: ignore[method-assign]
    source._fetch_yicai_news_rows = fake_fetch_yicai_rows  # type: ignore[method-assign]
    source._fetch_xueqiu_news_rows = fake_fetch_xueqiu_rows  # type: ignore[method-assign]
    import asyncio

    items = asyncio.run(source.fetch_news("科技"))
    sources = {item.source for item in items}

    assert "财联社" not in sources
    assert "东方财富" in sources
    assert "同花顺" in sources
    assert "第一财经" in sources


def test_news_keeps_sources_isolated_in_ui_grouping() -> None:
    news_resp = client.get("/api/v1/market/news", params={"category": "科技"})
    assert news_resp.status_code == 200
    body = news_resp.json()
    sources = {item["source"] for item in body}

    assert "东方财富" in sources
    assert "同花顺" in sources
    assert "第一财经" in sources
    assert "雪球" in sources


def test_tonghuashun_news_rank_parser_reads_zxrank() -> None:
    from apextran_app.modules.market.adapters.akshare_source import _parse_tonghuashun_rank_rows

    rows = _parse_tonghuashun_rank_rows(
        """
        <div class="tab-container">
          <ul class="item zxrank">
            <li><i>1.</i><a href="http://stock.10jqka.com.cn/20250822/c1.shtml">英伟达要求暂停生产H20芯片</a></li>
            <li><i>2.</i><a href="//yuanchuang.10jqka.com.cn/20250822/c2.shtml">独家资金:今日主力买入前10股</a></li>
          </ul>
        </div>
        """
    )

    assert [row["标题"] for row in rows] == ["英伟达要求暂停生产H20芯片", "独家资金:今日主力买入前10股"]
    assert rows[0]["来源"] == "同花顺新闻热榜"
    assert rows[0]["摘要"] == "同花顺新闻日排行第 1 位"
    assert rows[1]["链接"] == "https://yuanchuang.10jqka.com.cn/20250822/c2.shtml"


def test_tonghuashun_news_proxies_quicktiny_ths_hotlist_not_stock_rank() -> None:
    from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource

    source = AkshareMarketSource()
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "success": True,
                "data": [
                    {
                        "id": "T1dx5sv",
                        "title": "不用EUV提算力！先进封装走强",
                        "summary": "华天科技等公司因先进封装技术落地走强",
                        "subtitle": "成熟工艺实现算力提升",
                        "url": "https:https://t.10jqka.com.cn/topic.html?code=T1dx5sv",
                        "hotValue": 540000,
                        "category": "财经热点",
                        "source": "同花顺",
                        "publishTime": "7/7/2026, 9:54:08 PM",
                        "type": "topic",
                        "stocks": [
                            {"name": "华天科技", "code": "002185"},
                            {"name": "长电科技", "code": "600584"},
                        ],
                    }
                ],
            }

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        captured["headers"] = kwargs.get("headers")
        return FakeResponse()

    import asyncio
    from unittest.mock import patch

    with patch("requests.get", side_effect=fake_get):
        rows = asyncio.run(source._fetch_tonghuashun_news_rows())

    assert captured["url"] == "https://stock.quicktiny.cn/api/news/ths"
    assert captured["params"] == {"limit": 30}
    assert "User-Agent" in (captured["headers"] or {})
    assert rows[0]["来源"] == "同花顺"
    assert rows[0]["标题"] == "不用EUV提算力！先进封装走强"
    assert rows[0]["链接"] == "https://t.10jqka.com.cn/topic.html?code=T1dx5sv"
    assert rows[0]["热度"] == 540000
    # quicktiny's THS publishTime is the hotlist refresh time, not the item time.
    assert rows[0]["发布时间"] is None
    assert rows[0]["标签"] == ["财经热点", "topic", "华天科技", "长电科技"]
    assert rows[0]["股票"] == ["002185", "600584"]
    assert "股票" not in rows[0]["摘要"]


def test_tonghuashun_news_decodes_deep_topic_item_time() -> None:
    from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource

    source = AkshareMarketSource()

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "success": True,
                "data": [
                    {
                        "id": "dt_01KWV87ANQX11A90XAB9PDK1BN",
                        "title": "三星电子Q2利润 89.4万亿 ，再创历史新高",
                        "summary": "",
                        "subtitle": "三星赚翻了！预计Q2营业利润暴增1810%",
                        "url": "https:https://news.10jqka.com.cn/deep-topic/topic/dt_01KWV87ANQX11A90XAB9PDK1BN",
                        "hotValue": 514857,
                        "category": "财经热点",
                        "source": "同花顺",
                        "publishTime": "7/7/2026, 9:54:08 PM",
                        "type": "deep_topic",
                        "stocks": [],
                    }
                ],
            }

    def fake_get(*_args: object, **_kwargs: object) -> FakeResponse:
        return FakeResponse()

    import asyncio
    from unittest.mock import patch

    with patch("requests.get", side_effect=fake_get):
        [row] = asyncio.run(source._fetch_tonghuashun_news_rows())

    assert row["发布时间"] == "2026-07-06T08:20:26.423000+00:00"


def test_tonghuashun_news_falls_back_to_homepage_rank_when_quicktiny_unavailable() -> None:
    from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource

    source = AkshareMarketSource()
    captured: list[str] = []

    class QuicktinyResponse:
        def raise_for_status(self) -> None:
            raise RuntimeError("unavailable")

    class HomepageResponse:
        apparent_encoding = "gbk"
        text = """
        <ul class="item zxrank">
          <li><i>1.</i><a href="http://stock.10jqka.com.cn/20250822/c670558023.shtml">英伟达要求暂停生产H20芯片</a></li>
        </ul>
        """

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, **_kwargs: object) -> object:
        captured.append(url)
        if url == "https://stock.quicktiny.cn/api/news/ths":
            return QuicktinyResponse()
        return HomepageResponse()

    import asyncio
    from unittest.mock import patch

    with patch("requests.get", side_effect=fake_get):
        rows = asyncio.run(source._fetch_tonghuashun_news_rows())

    assert captured == ["https://stock.quicktiny.cn/api/news/ths", "https://news.10jqka.com.cn/"]
    assert rows[0]["来源"] == "同花顺新闻热榜"
    assert rows[0]["标题"] == "英伟达要求暂停生产H20芯片"


def test_fetch_news_preserves_tonghuashun_rank_order() -> None:
    from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource

    source = AkshareMarketSource()

    async def no_rows() -> list[dict[str, object]]:
        return []

    async def fake_ths_rows() -> list[dict[str, object]]:
        return [
            {
                "标题": "同花顺日排行第一",
                "摘要": "同花顺新闻日排行第 1 位",
                "内容": "同花顺新闻日排行第 1 位",
                "来源": "同花顺新闻热榜",
                "链接": "https://news.10jqka.com.cn/1.shtml",
                "发布时间": "2026-07-07T01:00:00+00:00",
            },
            {
                "标题": "同花顺日排行第二",
                "摘要": "同花顺新闻日排行第 2 位",
                "内容": "同花顺新闻日排行第 2 位",
                "来源": "同花顺新闻热榜",
                "链接": "https://news.10jqka.com.cn/2.shtml",
                "发布时间": "2026-07-07T02:00:00+00:00",
            },
        ]

    source._fetch_cls_telegraph_rows = no_rows  # type: ignore[method-assign]
    source._fetch_eastmoney_news_rows = no_rows  # type: ignore[method-assign]
    source._fetch_tonghuashun_news_rows = fake_ths_rows  # type: ignore[method-assign]
    source._fetch_yicai_news_rows = no_rows  # type: ignore[method-assign]
    source._fetch_xueqiu_news_rows = no_rows  # type: ignore[method-assign]

    import asyncio

    items = asyncio.run(source.fetch_news("科技"))

    assert [item.title for item in items] == ["同花顺日排行第一", "同花顺日排行第二"]


def test_tonghuashun_quicktiny_news_keeps_heat_tags_symbols_and_time() -> None:
    from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource

    source = AkshareMarketSource()
    [item] = source._news_from_rows(
        [
            {
                "标题": "不用EUV提算力！先进封装走强",
                "摘要": "华天科技等公司因先进封装技术落地走强",
                "内容": "华天科技等公司因先进封装技术落地走强",
                "来源": "同花顺",
                "链接": "https://t.10jqka.com.cn/topic.html?code=T1dx5sv",
                "发布时间": "7/7/2026, 9:54:08 PM",
                "热度": 540000,
                "分类": "财经热点",
                "标签": ["财经热点", "topic", "华天科技"],
                "股票": ["002185"],
            }
        ],
        tags=["综合", "精选"],
        sort_by_time=False,
    )

    assert item.source == "同花顺"
    assert item.heat == 540000
    assert item.tags == ["综合", "精选", "财经热点", "topic", "华天科技"]
    assert item.symbols == ["002185"]
    assert item.published_at.isoformat() == "2026-07-07T13:54:08+00:00"


def test_cls_telegraph_request_uses_initial_page_payload() -> None:
    from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource

    source = AkshareMarketSource()

    captured: dict[str, object] = {}

    def fake_get(url: str, *, params: dict[str, object], headers: dict[str, str], timeout: float):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["timeout"] = timeout

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "errno": 0,
                    "data": {
                        "roll_data": [
                            {
                                "id": 1,
                                "title": "财联社电报",
                                "content": "财联社电报内容",
                                "brief": "财联社电报内容",
                                "ctime": 1783249520,
                            }
                        ]
                    },
                }

        return FakeResponse()

    import asyncio
    from unittest.mock import patch

    with patch("requests.get", side_effect=fake_get):
        rows = asyncio.run(source._fetch_cls_telegraph_rows())

    assert rows
    assert captured["url"] == "https://www.cls.cn/api/cache"
    assert captured["params"] == {"rn": 30, "name": "telegraph"}


def test_eastmoney_news_proxies_quicktiny_hotlist_in_rank_order() -> None:
    from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource

    source = AkshareMarketSource()

    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "success": True,
                "data": [
                    {
                        "rank": i + 1,
                        "title": f"资讯热榜 {i}",
                        "summary": f"摘要 {i}",
                        "url": f"https://finance.eastmoney.com/a/{i}.html",
                        "source": "财联社",
                        "publishTime": f"2026-07-05 19:{59 - i:02d}:00",
                        "hotValue": 50000 - i,
                        "clickNum": 120000 - i,
                    }
                    for i in range(30)
                ],
            }

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return FakeResponse()

    import asyncio
    from unittest.mock import patch

    with patch("requests.get", side_effect=fake_get):
        rows = asyncio.run(source._fetch_eastmoney_news_rows())

    assert captured["url"] == "https://stock.quicktiny.cn/api/news/eastmoney"
    assert captured["params"] == {"limit": 30}
    # Routed to the 东方财富 tab, kept in the aggregator's rank order.
    assert all(row["来源"] == "东方财富" for row in rows)
    assert rows[0]["标题"] == "资讯热榜 0"
    assert rows[0]["链接"] == "https://finance.eastmoney.com/a/0.html"
    assert rows[0]["热度"] == 50000
    assert rows[0]["观看量"] == 120000
    assert rows[1]["标题"] == "资讯热榜 1"


def test_yicai_news_proxies_quicktiny_hotlist_in_rank_order() -> None:
    from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource

    source = AkshareMarketSource()

    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "success": True,
                "data": [
                    {
                        "id": "d7a439c43cfffc7d9803a23a331d18b1",
                        "title": "壹快评｜14人被骗去地铁站上假班，骗子得逞的根源是什么",
                        "summary": "一个健康成熟的现代社会，其运行基础应该是法治和契约。",
                        "url": "https://www.yicai.com/news/103208655.html",
                        "hotValue": "10热度",
                        "source": "第一财经",
                        "publishTime": "2026-05-31T03:50:13.000Z",
                        "category": "财经",
                        "isLive": False,
                        "isVideo": False,
                    },
                    {
                        "id": "02e8c80588a2b94fd639fcf61dc33653",
                        "title": "盘前必读丨长鑫科技IPO已提交注册",
                        "summary": "机构认为，科技股方向存在交易过渡拥挤。",
                        "url": "https://www.yicai.com/news/103204333.html",
                        "hotValue": "9热度",
                        "source": "第一财经",
                        "publishTime": "2026-05-27T23:58:39.000Z",
                        "category": "财经",
                        "isLive": False,
                        "isVideo": True,
                    },
                ],
            }

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return FakeResponse()

    import asyncio
    from unittest.mock import patch

    with patch("requests.get", side_effect=fake_get):
        rows = asyncio.run(source._fetch_yicai_news_rows())

    assert captured["url"] == "https://stock.quicktiny.cn/api/news/yicai"
    assert captured["params"] == {"limit": 30}
    assert all(row["来源"] == "第一财经" for row in rows)
    assert rows[0]["标题"] == "壹快评｜14人被骗去地铁站上假班，骗子得逞的根源是什么"
    assert rows[0]["热度"] == "10热度"
    assert rows[0]["标签"] == ["财经"]
    assert rows[1]["标签"] == ["财经", "视频"]

    [item] = source._news_from_rows(rows[:1], tags=["综合", "精选"], sort_by_time=False)
    assert item.source == "第一财经"
    assert item.heat == 10
    assert item.tags == ["综合", "精选", "财经"]
    assert item.published_at.isoformat() == "2026-05-31T03:50:13+00:00"


def test_xueqiu_news_reads_hot_event_ranking_with_heat_and_no_time() -> None:
    from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource

    source = AkshareMarketSource()

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "success": True,
                "data": [
                    {
                        "title": "#端侧AI概念震荡走强，瑞芯微涨停#",
                        "content": "早盘端侧AI概念震荡走强，瑞芯微涨停。",
                        "reason": "热度值 170.8万",
                        "url": "https://xueqiu.com/hashtag/abc",
                    }
                ],
            }

    class FakeSession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}
            self.urls: list[str] = []

        def get(self, url: str, **_kwargs: object) -> FakeResponse:
            self.urls.append(url)
            return FakeResponse()

    session = FakeSession()

    import asyncio
    from unittest.mock import patch

    with patch("requests.Session", return_value=session):
        rows = asyncio.run(source._fetch_xueqiu_news_rows())

    # Homepage is hit first to seed the anonymous cookie, then the hot_event feed.
    assert session.urls == [
        "https://xueqiu.com/hq",
        "https://xueqiu.com/query/v1/hot_event/tag.json",
    ]
    assert rows[0]["来源"] == "雪球"
    assert rows[0]["标题"] == "端侧AI概念震荡走强，瑞芯微涨停"  # hashes unwrapped
    assert rows[0]["发布时间"] is None  # heat ranking has no publish time

    # fetch_news tags 雪球 rows "精选" only (no 综合), and the reason parses to heat.
    [item] = source._news_from_rows(rows[:1], tags=["精选"], sort_by_time=False)
    assert item.source == "雪球"
    assert item.tags == ["精选"]  # 热度 + 精选 + 雪球 is all that shows
    assert item.heat == 1_708_000  # "170.8万" → 1_708_000
    assert item.published_at is None  # no time → UI hides the timestamp


def test_naive_news_timestamp_is_parsed_as_china_time() -> None:
    from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource

    source = AkshareMarketSource()
    item = source._to_news(
        {
            "标题": "东方财富热榜资讯",
            "内容": "内容",
            "摘要": "内容",
            "来源": "东方财富",
            "链接": "https://finance.eastmoney.com/a/test.html",
            "发布时间": "2026-07-05 17:29:00",
        },
        tags=["综合", "精选"],
        symbols=[],
    )

    assert item.published_at.isoformat() == "2026-07-05T09:29:00+00:00"


def test_news_keeps_older_eastmoney_items_after_merge() -> None:
    from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource

    source = AkshareMarketSource()

    async def fake_cls_rows() -> list[dict[str, object]]:
        return [
            {
                "标题": f"财联社 {i}",
                "内容": "财联社内容",
                "摘要": "财联社内容",
                "来源": "财联社",
                "链接": f"https://www.cls.cn/detail/{i}",
                "发布时间": f"2026-07-05T19:{59 - i:02d}:00+00:00",
            }
            for i in range(10)
        ]

    async def fake_ths_rows() -> list[dict[str, object]]:
        return [
            {
                "标题": f"同花顺 {i}",
                "内容": "同花顺内容",
                "摘要": "同花顺内容",
                "来源": "同花顺",
                "链接": f"https://news.10jqka.com.cn/{i}.shtml",
                "发布时间": f"2026-07-05T18:{59 - i:02d}:00+00:00",
            }
            for i in range(20)
        ]

    async def fake_eastmoney_rows() -> list[dict[str, object]]:
        return [
            {
                "标题": f"东方财富 {i}",
                "内容": "东方财富内容",
                "摘要": "东方财富内容",
                "来源": "东方财富",
                "链接": f"https://finance.eastmoney.com/a/{i}.html",
                "发布时间": f"2026-07-04T08:{i:02d}:00+00:00",
            }
            for i in range(20)
        ]

    async def fake_yicai_rows() -> list[dict[str, object]]:
        return [
            {
                "标题": f"第一财经 {i}",
                "内容": "第一财经内容",
                "摘要": "第一财经内容",
                "来源": "第一财经",
                "链接": f"https://www.yicai.com/news/{i}.html",
                "发布时间": f"2026-07-03T08:{i:02d}:00+00:00",
                "热度": f"{20 - i}热度",
            }
            for i in range(20)
        ]

    async def no_rows() -> list[dict[str, object]]:
        return []

    source._fetch_cls_telegraph_rows = fake_cls_rows  # type: ignore[method-assign]
    source._fetch_tonghuashun_news_rows = fake_ths_rows  # type: ignore[method-assign]
    source._fetch_eastmoney_news_rows = fake_eastmoney_rows  # type: ignore[method-assign]
    source._fetch_yicai_news_rows = fake_yicai_rows  # type: ignore[method-assign]
    source._fetch_xueqiu_news_rows = no_rows  # type: ignore[method-assign]

    import asyncio

    items = asyncio.run(source.fetch_news("科技"))
    counts: dict[str, int] = {}
    for item in items:
        counts[item.source] = counts.get(item.source, 0) + 1

    assert len(items) == 40
    assert counts["财联社"] == 10
    assert counts["同花顺"] == 10
    assert counts["东方财富"] == 10
    assert counts["第一财经"] == 10


def test_flash_aggregates_cls_and_wallstreetcn_newest_first() -> None:
    """7x24 快讯 merges 财联社电报 + 华尔街见闻, tagged by source, newest-first."""
    from apextran_app.modules.market.adapters.akshare_source import AkshareMarketSource

    source = AkshareMarketSource()

    async def fake_cls_rows() -> list[dict[str, object]]:
        return [
            {
                "标题": "财联社电报",
                "内容": "财联社快讯内容",
                "来源": "财联社",
                "链接": "https://www.cls.cn/detail/1",
                "发布时间": "2026-07-05T09:00:00+00:00",
            }
        ]

    async def fake_wscn_rows() -> list[dict[str, object]]:
        return [
            {
                "标题": "",
                "内容": "华尔街见闻快讯内容",
                "来源": "华尔街见闻",
                "链接": "https://wallstreetcn.com/livenews/1",
                "发布时间": 1783436872,  # unix seconds, later than the CLS row
            }
        ]

    source._fetch_cls_telegraph_rows = fake_cls_rows  # type: ignore[method-assign]
    source._fetch_wallstreetcn_flash_rows = fake_wscn_rows  # type: ignore[method-assign]

    import asyncio

    items = asyncio.run(source.fetch_flash())
    sources = [item.source for item in items]

    assert "财联社" in sources
    assert "华尔街见闻" in sources
    # 华尔街见闻 row is newer → sorts first.
    assert items[0].source == "华尔街见闻"
    assert items[0].url == "https://wallstreetcn.com/livenews/1"
    # published_at is monotonically non-increasing (newest-first).
    times = [item.published_at for item in items]
    assert times == sorted(times, reverse=True)


def test_mock_flash_cls_mirrors_news_cls() -> None:
    """7x24 快讯 财联社 shows the same content as 精选资讯 财经热点 财联社 (mock)."""
    import asyncio

    from apextran_app.modules.market.adapters.mock_source import MockMarketSource

    source = MockMarketSource()
    news = asyncio.run(source.fetch_news("综合"))
    flash = asyncio.run(source.fetch_flash())

    news_cls = {item.title for item in news if item.source == "财联社"}
    flash_cls = {item.content for item in flash if item.source == "财联社"}

    assert news_cls
    assert news_cls == flash_cls
