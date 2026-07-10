"""Deterministic mock source — lets the whole chain run without real upstreams.

Data is generated from a fixed seed offset by the current minute so the UI shows
plausible movement on refresh, but no network/keys are needed (M1).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..domain.models import FlashItem, FlashLevel, HotItem, NewsItem, StockSearchItem

_SAMPLE = [
    ("600519", "贵州茅台", "白酒"),
    ("300750", "宁德时代", "电池"),
    ("002594", "比亚迪", "汽车整车"),
    ("601318", "中国平安", "保险"),
    ("000858", "五粮液", "白酒"),
    ("688981", "中芯国际", "半导体"),
    ("601899", "紫金矿业", "有色金属"),
    ("300059", "东方财富", "证券"),
]

_CLS_TELEGRAPH_URL = "https://www.cls.cn/telegraph"
# 财联社电报 sample feed. The same list backs both the 精选资讯 财经热点 财联社 tab
# and the 7x24 快讯 财联社 tab, mirroring production where both read CLS telegraph —
# so the two 财联社 views always show identical content.
_CLS_TELEGRAPH = [
    "市场结构性行情延续,资金聚焦高景气赛道。",
    "AI算力需求超预期,国产芯片产业链集体走强。",
    "北向资金今日净买入超50亿元,加仓电子与新能源。",
    "多家券商上调新能源板块评级,看好中长期机会。",
    "大模型商业化落地加速,应用端公司获资金青睐。",
    "半导体设备板块异动拉升,机构关注度明显提升。",
]


def _now() -> datetime:
    return datetime.now(UTC)


class MockMarketSource:
    """In-memory ``MarketSource`` implementation."""

    async def fetch_hotlist(self) -> list[HotItem]:
        now = _now()
        minute = now.minute
        items: list[HotItem] = []
        for i, (symbol, name, concept) in enumerate(_SAMPLE):
            items.append(
                HotItem(
                    rank=i + 1,
                    symbol=symbol,
                    name=name,
                    boards=(minute + i) % 7,
                    change_pct=round(((minute + i * 3) % 21) - 10 + 0.05, 2),
                    reason="资金净流入居前" if i % 2 == 0 else "题材催化",
                    concept=concept,
                    hot_score=round(100 - i * 7.5 + minute * 0.2, 2),
                    latest_price=round(10 + i * 3.6 + minute * 0.03, 2),
                    eastmoney_rank=i + 1,
                    tonghuashun_rank=i + 2 if i < 6 else None,
                    kai_pan_la_rank=i + 3 if i < 5 else None,
                    tao_gu_ba_rank=i + 4 if i < 4 else None,
                    sources=["东方财富", "同花顺"] + (["开盘啦"] if i < 5 else []) + (["淘股吧"] if i < 4 else []),
                    updated_at=now,
                )
            )
        return items

    async def search_stocks(self, query: str, limit: int = 20) -> list[StockSearchItem]:
        now = _now()
        keyword = query.strip().lower()
        if not keyword:
            return []
        matches = [
            StockSearchItem(
                symbol=symbol,
                name=name,
                market=_market_for_symbol(symbol),
                latest_price=round(10 + index * 3.6 + now.minute * 0.03, 2),
                change_pct=round(((now.minute + index * 3) % 21) - 10 + 0.05, 2),
                concept=concept,
                source="MockWire",
                updated_at=now,
            )
            for index, (symbol, name, concept) in enumerate(_SAMPLE)
            if keyword in f"{symbol} {name}".lower()
        ]
        return matches[: max(1, min(limit, 50))]

    async def list_stock_instruments(self) -> list[StockSearchItem]:
        now = _now()
        return [
            StockSearchItem(
                symbol=symbol,
                name=name,
                market=_market_for_symbol(symbol),
                latest_price=None,
                change_pct=None,
                concept=concept,
                source="MockWire股票池",
                updated_at=now,
            )
            for symbol, name, concept in _SAMPLE
        ]

    async def fetch_headlines(self, symbol: str | None = None) -> list[NewsItem]:
        now = _now()
        pool = [s for s in _SAMPLE if symbol is None or s[0] == symbol] or _SAMPLE
        return [
            NewsItem(
                id=f"hl-{sym}-{now:%Y%m%d%H%M}",
                title=f"{name}({sym})盘中异动,成交显著放量",
                summary=f"{name}今日受行业消息带动,资金关注度上升。",
                source="MockWire",
                url=f"https://example.com/news/{sym}",
                tags=["个股", "异动"],
                symbols=[sym],
                sentiment=0.3,
                published_at=now,
            )
            for sym, name, _concept in pool[:6]
        ]

    async def fetch_news(self, category: str | None = None) -> list[NewsItem]:
        now = _now()
        cat = category or "综合"
        items: list[NewsItem] = []
        # 财联社 电报 → emit the shared CLS telegraph list so this tab shows the
        # exact same content as the 7x24 快讯 财联社 tab (both read this feed).
        for i, headline in enumerate(_CLS_TELEGRAPH):
            items.append(
                NewsItem(
                    id=f"news-财联社-{i}-{now:%Y%m%d%H%M}",
                    title=headline,
                    summary=headline,
                    source="财联社",
                    url=_CLS_TELEGRAPH_URL,
                    tags=[cat, "精选"],
                    symbols=[],
                    sentiment=0.1,
                    published_at=now - timedelta(minutes=i),
                )
            )
        samples = [
            ("东方财富", "https://kuaixun.eastmoney.com/7_24.html", "北向资金盘中波动加大"),
            ("同花顺", "https://news.10jqka.com.cn/realtimenews.html", "算力板块午后持续活跃"),
            ("第一财经", "https://www.yicai.com/news/", "科技股估值分化加剧"),
            ("雪球", "https://xueqiu.com/today", "半导体板块讨论热度居前"),
        ]
        for i, (source, url, headline) in enumerate(samples, start=1):
            items.append(
                NewsItem(
                    id=f"news-{source}-{i}-{now:%Y%m%d%H%M}",
                    title=f"[{cat}] {headline}",
                    summary="编辑精选:板块轮动加快,关注高景气方向。",
                    source=source,
                    url=url,
                    # 雪球 is a heat ranking with no category — show just "精选" (no 综合).
                    tags=["精选"] if source == "雪球" else [cat, "精选"],
                    symbols=[],
                    sentiment=0.1 * (i - 1),
                    heat=1_708_000 if source == "雪球" else (10 if source == "第一财经" else None),
                    # 雪球 热榜 has no publish time — leave it unset so the UI hides it.
                    published_at=None if source == "雪球" else now,
                )
            )
        return items

    async def fetch_ai_hotspots(self) -> list[NewsItem]:
        now = _now()
        samples = [
            (
                "AI算力硬件中报预增企业集中披露",
                "存储芯片、光模块、PCB 等方向热度上升，多平台资金关注度提升。",
                ["同花顺", "东方财富", "百度"],
                658_927,
            ),
            (
                "高盛预计人形机器人市场十年倍数增长",
                "机器人产业链进入密集催化期，设备、传感器与执行器方向关注度提升。",
                ["同花顺", "微博"],
                437_242,
            ),
            (
                "先进封装技术推动成熟工艺算力提升",
                "半导体封装、EDA 与国产替代方向进入财经热榜。",
                ["同花顺", "第一财经", "头条"],
                355_050,
            ),
        ]
        return [
            NewsItem(
                id=f"ai-hotspot-{i}-{now:%Y%m%d%H%M}",
                title=title,
                summary=summary,
                source="AI智能热榜",
                url="https://stock.quicktiny.cn/news-hotlist",
                tags=["财经热点", *platforms],
                symbols=[],
                sentiment=0.1,
                heat=heat,
                published_at=now - timedelta(minutes=i * 3),
            )
            for i, (title, summary, platforms, heat) in enumerate(samples)
        ]

    async def fetch_flash(self) -> list[FlashItem]:
        now = _now()
        items: list[FlashItem] = []
        # 财联社 tab mirrors the 精选资讯 财经热点 财联社 list exactly — same shared
        # CLS telegraph feed, same text, same order.
        for i, headline in enumerate(_CLS_TELEGRAPH):
            items.append(
                FlashItem(
                    id=f"flash-财联社-{i}-{now:%Y%m%d%H%M}",
                    content=headline,
                    source="财联社",
                    url=_CLS_TELEGRAPH_URL,
                    level=FlashLevel.normal,
                    symbols=[],
                    published_at=now - timedelta(minutes=i),
                )
            )
        # 华尔街见闻 wire — distinct global-macro flashes (AI keywords included so
        # the AI聚合 tab has content without a network call).
        wscn = [
            "隔夜美股科技板块普涨,AI 概念领涨纳指。",
            "国际油价走高,能源与航运板块表现活跃。",
            "美联储官员发表讲话,市场关注后续加息路径。",
            "全球大模型竞赛升温,算力与芯片需求持续扩张。",
        ]
        for i, content in enumerate(wscn):
            items.append(
                FlashItem(
                    id=f"flash-华尔街见闻-{i}-{now:%Y%m%d%H%M}",
                    content=content,
                    source="华尔街见闻",
                    url="https://wallstreetcn.com/live/global",
                    level=FlashLevel.important if i == 0 else FlashLevel.normal,
                    symbols=[],
                    published_at=now - timedelta(minutes=i),
                )
            )
        # Interleave both wires newest-first, like the live aggregator does.
        items.sort(key=lambda item: item.published_at, reverse=True)
        return items


def _market_for_symbol(symbol: str) -> str:
    if symbol.startswith("6"):
        return "沪市A股"
    if symbol.startswith(("0", "3")):
        return "深市A股"
    if symbol.startswith(("4", "8", "92")):
        return "北交所"
    return "A股"
