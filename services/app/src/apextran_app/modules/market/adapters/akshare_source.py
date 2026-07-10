"""akshare-backed ``MarketSource`` (M2, real A-share data).

akshare is an optional extra (``uv sync --extra sources``) and its calls are
blocking + pandas-based, so every call runs in a worker thread. Column names
vary across akshare versions — the ``_col`` helper is tolerant, and mapping is
best-effort; tune against the installed version if a field comes back empty.

Not exercised in CI (needs network to upstream). The worker calls these on a
schedule; failures propagate so the caller can fall back to the last cached
snapshot (stale-while-revalidate, added with Redis in M2).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from ..domain.models import FlashItem, FlashLevel, HotItem, NewsItem, StockSearchItem

_NEWS_ITEMS_PER_SOURCE = 10
_CN_TZ = ZoneInfo("Asia/Shanghai")


def _now() -> datetime:
    return datetime.now(UTC)


def _col(row: dict[str, Any], *names: str, default: Any = "") -> Any:
    """Return the first present column among ``names`` (version-tolerant)."""
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return default


def _stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]  # noqa: S324 — id only, not security


class _TonghuashunRankParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, Any]] = []
        self._in_rank_list = False
        self._rank_list_depth = 0
        self._in_link = False
        self._link_href = ""
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        if tag == "ul":
            if self._in_rank_list:
                self._rank_list_depth += 1
            elif _has_classes(attr.get("class", ""), {"item", "zxrank"}):
                self._in_rank_list = True
                self._rank_list_depth = 1
            return

        if self._in_rank_list and tag == "a":
            self._in_link = True
            self._link_href = attr.get("href", "")
            self._link_text = []

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._link_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._in_link and tag == "a":
            title = " ".join("".join(self._link_text).split())
            if title and self._link_href:
                rank = len(self.rows) + 1
                summary = f"同花顺新闻日排行第 {rank} 位"
                self.rows.append({
                    "标题": title,
                    "摘要": summary,
                    "内容": summary,
                    "来源": "同花顺新闻热榜",
                    "链接": _normalize_tonghuashun_url(self._link_href),
                    "发布时间": _now().isoformat(),
                })
            self._in_link = False
            self._link_href = ""
            self._link_text = []
            return

        if self._in_rank_list and tag == "ul":
            self._rank_list_depth -= 1
            if self._rank_list_depth <= 0:
                self._in_rank_list = False


def _parse_tonghuashun_rank_rows(html: str) -> list[dict[str, Any]]:
    parser = _TonghuashunRankParser()
    parser.feed(html)
    return parser.rows


def _has_classes(class_value: str, required: set[str]) -> bool:
    classes = {part.strip() for part in class_value.split() if part.strip()}
    return required <= classes


def _normalize_tonghuashun_url(value: str) -> str:
    raw = value.strip()
    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith("/"):
        return f"https://news.10jqka.com.cn{raw}"
    return raw


def _normalize_external_url(value: str, default: str = "") -> str:
    raw = value.strip()
    if not raw:
        return default
    if raw.startswith("https:https://"):
        return raw.replace("https:https://", "https://", 1)
    if raw.startswith("http:http://"):
        return raw.replace("http:http://", "http://", 1)
    if raw.startswith("//"):
        return f"https:{raw}"
    return raw


def _quicktiny_ths_summary(entry: dict[str, Any]) -> str:
    summary = str(entry.get("summary") or "").strip()
    subtitle = str(entry.get("subtitle") or "").strip()
    if summary and subtitle and subtitle not in summary:
        return f"{summary} {subtitle}"
    return summary or subtitle


def _merge_unique(*groups: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if isinstance(group, str):
            values: list[Any] = [group]
        elif isinstance(group, (list, tuple, set)):
            values = list(group)
        else:
            continue
        for value in values:
            text = str(value or "").strip()
            if text and text not in seen:
                merged.append(text)
                seen.add(text)
    return merged


def _news_tags_from_row(row: dict[str, Any]) -> list[str]:
    return _merge_unique(
        _col(row, "分类", "category", default=""),
        _col(row, "标签", "tags", default=[]),
    )


def _news_symbols_from_row(row: dict[str, Any]) -> list[str]:
    raw = _col(row, "股票", "symbols", default=[])
    if isinstance(raw, str):
        values: list[Any] = [raw]
    elif isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        values = []
    return [symbol for symbol in (str(value or "").strip() for value in values) if symbol]


def _tonghuashun_entry_publish_time(entry: dict[str, Any]) -> str | None:
    """Best-effort per-item publish time for quicktiny's THS hotlist rows.

    The feed-level ``publishTime`` returned by quicktiny is the hotlist refresh
    time and is identical across rows; do not use it as an article timestamp.
    """

    raw = entry.get("raw") if isinstance(entry.get("raw"), dict) else {}
    for container in (entry, raw):
        for key in ("publishedAt", "published_at", "publish_time", "publishDate", "create_time", "created_at", "ctime"):
            parsed = _parse_datetime_value(container.get(key))
            if parsed is not None:
                return parsed.isoformat()

    for value in (entry.get("id"), raw.get("code")):
        parsed = _decode_ulid_datetime(value)
        if parsed is not None:
            return parsed.isoformat()

    return None


def _parse_datetime_value(value: Any) -> datetime | None:
    return _now_from({"发布时间": value})


def _decode_ulid_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if text.startswith("dt_"):
        text = text[3:]
    if len(text) < 10:
        return None
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    try:
        timestamp_ms = 0
        for char in text[:10].upper():
            timestamp_ms = timestamp_ms * 32 + alphabet.index(char)
    except ValueError:
        return None
    parsed = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    if 2020 <= parsed.year <= 2035:
        return parsed
    return None


# A stock's industry board (行业) is effectively static, so cache it for a day
# and only ever pay the per-symbol lookup for names newly on the hotlist.
_SECTOR_TTL_SECONDS = 24 * 3600
_SECTOR_CONCURRENCY = 8
_SECTOR_TIMEOUT_SECONDS = 8.0
# Per-source cap: akshare uses requests with no timeout, so a single wedged
# upstream (seen on 同花顺 量价齐升) would otherwise hang the whole refresh. Cap
# it and degrade to whatever other sources returned.
_SOURCE_TIMEOUT_SECONDS = 15.0
_CLS_TELEGRAPH_URL = "https://www.cls.cn/telegraph"
_CLS_CACHE_URL = "https://www.cls.cn/api/cache"
_EASTMONEY_HOME_URL = "https://www.eastmoney.com/"
# quicktiny's /news-hotlist page fetches these endpoints and renders their
# hotValue directly. Use the same ranked feeds so our source tabs match that
# page's article/topic heat lists, not stock popularity lists.
_QUICKTINY_EASTMONEY_URL = "https://stock.quicktiny.cn/api/news/eastmoney"
_QUICKTINY_THS_URL = "https://stock.quicktiny.cn/api/news/ths"
_QUICKTINY_YICAI_URL = "https://stock.quicktiny.cn/api/news/yicai"
_QUICKTINY_SINA_URL = "https://stock.quicktiny.cn/api/news/sina"
_QUICKTINY_DOUYIN_URL = "https://stock.quicktiny.cn/api/news/douyin"
_QUICKTINY_WEIBO_URL = "https://stock.quicktiny.cn/api/news/weibo"
_QUICKTINY_BAIDU_URL = "https://stock.quicktiny.cn/api/news/baidu"
_QUICKTINY_TOUTIAO_URL = "https://stock.quicktiny.cn/api/news/toutiao"
_QUICKTINY_NEWS_REFERER = "https://stock.quicktiny.cn/news-hotlist"
_EASTMONEY_NEWS_LIMIT = 30
_YICAI_NEWS_LIMIT = 30
_AI_HOTSPOT_SOURCE_LIMIT = 30
_AI_HOTSPOT_RESULT_LIMIT = 50
_SMART_SOURCE_WEIGHTS = {
    "eastmoney": 12,
    "ths": 11,
    "yicai": 10,
    "sina": 9,
    "weibo": 10,
    "toutiao": 9,
    "douyin": 8,
    "baidu": 8,
}
_FINANCE_HOTSPOT_KEYWORDS = [
    "股票",
    "股市",
    "A股",
    "港股",
    "美股",
    "上证",
    "深证",
    "创业板",
    "科创板",
    "涨停",
    "跌停",
    "涨幅",
    "跌幅",
    "成交量",
    "市值",
    "PE",
    "PB",
    "基金",
    "债券",
    "期货",
    "外汇",
    "黄金",
    "原油",
    "比特币",
    "数字货币",
    "央行",
    "货币政策",
    "利率",
    "汇率",
    "GDP",
    "CPI",
    "PMI",
    "通胀",
    "IPO",
    "重组",
    "并购",
    "分红",
    "配股",
    "增发",
    "退市",
    "新能源",
    "芯片",
    "人工智能",
    "5G",
    "新基建",
    "碳中和",
    "新材料",
    "房地产",
    "银行",
    "保险",
    "券商",
    "医药",
    "消费",
    "科技",
    "军工",
    "财报",
    "业绩",
    "营收",
    "净利润",
    "亏损",
    "盈利",
    "财务",
    "监管",
    "证监会",
    "银保监会",
    "金融",
    "投资",
    "融资",
    "上市",
    "经济",
    "宏观",
    "政策",
    "改革",
    "开放",
    "贸易",
    "出口",
    "进口",
]
_TONGHUASHUN_NEWS_HOME_URL = "https://news.10jqka.com.cn/"
_TONGHUASHUN_REALTIME_URL = "https://news.10jqka.com.cn/realtimenews.html"
_TONGHUASHUN_NEWS_RANK_LIMIT = 30
# 雪球资讯热榜 — quicktiny has no xueqiu feed, so read xueqiu's own 今日话题 hot
# events directly. The API host rejects tokenless calls (error 400016); a plain
# GET of the homepage first seeds the anonymous `u` cookie the endpoint checks.
_XUEQIU_COOKIE_SEED_URL = "https://xueqiu.com/hq"
_XUEQIU_HOT_EVENT_URL = "https://xueqiu.com/query/v1/hot_event/tag.json"
_XUEQIU_HOME_URL = "https://xueqiu.com/today"
_XUEQIU_NEWS_LIMIT = 10
# 华尔街见闻 7x24 快讯 — the public global live feed powering wallstreetcn.com/live.
_WSCN_LIVES_URL = "https://api-one-wscn.awtmt.com/apiv1/content/lives"
_WSCN_FLASH_LIMIT = 30
_FLASH_ITEMS_PER_SOURCE = 40
_STOCK_SEARCH_POOL_TTL_SECONDS = 300
_STOCK_SEARCH_MAX_LIMIT = 50
_TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
_WEB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": _CLS_TELEGRAPH_URL,
}
class AkshareMarketSource:
    """Maps akshare payloads onto the normalized domain models."""

    def __init__(self) -> None:
        # symbol -> (industry, expires_at monotonic seconds)
        self._sector_cache: dict[str, tuple[str, float]] = {}
        # A-share spot rows are a search pool; cache once per process instead of
        # pulling the full market table for every typed keyword.
        self._stock_search_rows_cache: tuple[list[dict[str, Any]], float] | None = None
        self._stock_pool_rows_cache: tuple[list[dict[str, Any]], float] | None = None

    async def fetch_hotlist(self) -> list[HotItem]:  # noqa: C901 — linear merge of 4 ranked sources; splitting scatters tightly-coupled ranking
        now = _now()
        eastmoney_rows, eastmoney_up_rows, ths_rise_rows, ths_volume_rows = await asyncio.gather(
            self._safe_records("eastmoney.hot_rank", lambda ak: ak.stock_hot_rank_em()),
            self._safe_records("eastmoney.hot_up", lambda ak: ak.stock_hot_up_em()),
            self._safe_records("tonghuashun.lxsz", lambda ak: ak.stock_rank_lxsz_ths()),
            self._safe_records("tonghuashun.ljqs", lambda ak: ak.stock_rank_ljqs_ths()),
        )

        merged: dict[str, HotItem] = {}

        for i, row in enumerate(eastmoney_rows):
            symbol = _normalize_symbol(_col(row, "代码", "股票代码", "symbol"))
            if not symbol:
                continue
            item = HotItem(
                rank=int(_col(row, "当前排名", "排名", default=i + 1)),
                symbol=symbol,
                name=str(_col(row, "股票名称", "名称", "name", default=symbol)),
                boards=0,
                change_pct=_to_float(_col(row, "涨跌幅", "涨跌额", default=0.0)),
                reason=str(_col(row, "简介", "reason", default="东方财富人气榜")),
                hot_score=max(0.0, 200.0 - i * 2.0),
                latest_price=_to_optional_float(_col(row, "最新价", "现价", default=None)),
                eastmoney_rank=int(_col(row, "当前排名", "排名", default=i + 1)),
                sources=["东方财富"],
                updated_at=now,
            )
            merged[symbol] = item

        for i, row in enumerate(eastmoney_up_rows):
            symbol = _normalize_symbol(_col(row, "代码", "股票代码", "symbol"))
            if not symbol:
                continue
            item = merged.get(symbol)
            if item is None:
                item = HotItem(
                    rank=1000 + i,
                    symbol=symbol,
                    name=str(_col(row, "股票名称", "名称", "name", default=symbol)),
                    boards=0,
                    change_pct=_to_float(_col(row, "涨跌幅", default=0.0)),
                    reason="东方财富飙升榜",
                    hot_score=max(0.0, 120.0 - i * 1.5),
                    latest_price=_to_optional_float(_col(row, "最新价", "现价", default=None)),
                    eastmoney_rank=None,
                    sources=["东方财富"],
                    updated_at=now,
                )
                merged[symbol] = item
            item.reason = item.reason or "东方财富飙升榜"
            item.hot_score += max(0.0, 80.0 - i)
            if "东方财富" not in item.sources:
                item.sources.append("东方财富")

        for i, row in enumerate(ths_rise_rows):
            symbol = _normalize_symbol(_col(row, "股票代码", "代码", default=""))
            if not symbol:
                continue
            item = merged.get(symbol)
            if item is None:
                item = HotItem(
                    rank=2000 + i,
                    symbol=symbol,
                    name=str(_col(row, "股票简称", "名称", default=symbol)),
                    boards=0,
                    change_pct=_to_float(_col(row, "连续涨跌幅", "阶段涨幅", default=0.0)),
                    reason="同花顺连续上涨",
                    hot_score=max(0.0, 90.0 - i),
                    latest_price=_to_optional_float(_col(row, "收盘价", "最新价", default=None)),
                    tonghuashun_rank=i + 1,
                    sources=["同花顺"],
                    updated_at=now,
                )
                merged[symbol] = item
            item.boards = max(item.boards, _to_int(_col(row, "连涨天数", default=0)))
            item.tonghuashun_rank = min_non_null(item.tonghuashun_rank, i + 1)
            item.hot_score += max(0.0, 70.0 - i)
            item.reason = merge_reason(item.reason, "同花顺连续上涨")
            item.concept = item.concept or str(_col(row, "所属行业", default="")).strip()
            if "同花顺" not in item.sources:
                item.sources.append("同花顺")

        for i, row in enumerate(ths_volume_rows):
            symbol = _normalize_symbol(_col(row, "股票代码", "代码", default=""))
            if not symbol:
                continue
            item = merged.get(symbol)
            if item is None:
                item = HotItem(
                    rank=3000 + i,
                    symbol=symbol,
                    name=str(_col(row, "股票简称", "名称", default=symbol)),
                    boards=0,
                    change_pct=_to_float(_col(row, "阶段涨幅", default=0.0)),
                    reason="同花顺量价齐升",
                    hot_score=max(0.0, 60.0 - i),
                    latest_price=_to_optional_float(_col(row, "最新价", default=None)),
                    tonghuashun_rank=i + 1,
                    sources=["同花顺"],
                    updated_at=now,
                )
                merged[symbol] = item
            item.tonghuashun_rank = min_non_null(item.tonghuashun_rank, i + 1)
            item.hot_score += max(0.0, 55.0 - i)
            item.reason = merge_reason(item.reason, "同花顺量价齐升")
            item.concept = item.concept or str(_col(row, "所属行业", default="")).strip()
            if "同花顺" not in item.sources:
                item.sources.append("同花顺")

        items = list(merged.values())
        if not items:
            return []

        items.sort(
            key=lambda item: (
                -item.hot_score,
                item.eastmoney_rank or 9_999,
                item.tonghuashun_rank or 9_999,
                -item.boards,
            )
        )
        for index, item in enumerate(items, start=1):
            item.rank = index
        top = items[:50]
        await self._enrich_concepts(top)
        return top

    async def search_stocks(self, query: str, limit: int = 20) -> list[StockSearchItem]:
        cleaned = query.strip()
        if not cleaned:
            return []
        bounded_limit = max(1, min(limit, _STOCK_SEARCH_MAX_LIMIT))
        rows = await self._stock_search_rows()
        if rows:
            results = _build_stock_search_results(rows, cleaned, bounded_limit)
            if results:
                return results

        exact_quote = await self._fetch_tencent_stock_match(cleaned)
        if exact_quote is not None:
            return [exact_quote]

        hotlist = await self.fetch_hotlist()
        return [
            StockSearchItem(
                symbol=item.symbol,
                name=item.name,
                market=_market_for_symbol(item.symbol),
                latest_price=item.latest_price,
                change_pct=item.change_pct,
                concept=item.concept,
                source="热榜兜底",
                updated_at=item.updated_at,
            )
            for item in hotlist
            if _stock_matches_query(item.symbol, item.name, cleaned)
        ][:bounded_limit]

    async def list_stock_instruments(self) -> list[StockSearchItem]:
        rows = await self._stock_pool_rows()
        if rows:
            return _build_stock_pool_results(rows, source="akshare股票基础表")
        rows = await self._stock_search_rows()
        if rows:
            return _build_stock_pool_results(rows)
        return []

    async def _stock_pool_rows(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        cached = self._stock_pool_rows_cache
        if cached is not None and cached[1] > now:
            return cached[0]

        rows = await self._safe_records("akshare.stock_info_a_code_name", lambda ak: ak.stock_info_a_code_name())
        if rows:
            self._stock_pool_rows_cache = (rows, now + _STOCK_SEARCH_POOL_TTL_SECONDS)
            return rows
        return cached[0] if cached is not None else []

    async def _stock_search_rows(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        cached = self._stock_search_rows_cache
        if cached is not None and cached[1] > now:
            return cached[0]

        rows = await self._safe_records("eastmoney.stock_search", lambda ak: ak.stock_zh_a_spot_em())
        if rows:
            self._stock_search_rows_cache = (rows, now + _STOCK_SEARCH_POOL_TTL_SECONDS)
            return rows

        # If refresh fails, keep serving the previous pool; search is better with
        # slightly stale names than with a slow empty result.
        return cached[0] if cached is not None else []

    async def _fetch_tencent_stock_match(self, query: str) -> StockSearchItem | None:
        symbol = _normalize_symbol(query)
        if len(symbol) != 6 or not symbol.isdigit():
            return None

        def _run() -> StockSearchItem | None:
            import requests

            response = requests.get(
                _TENCENT_QUOTE_URL + _tencent_symbol(symbol),
                headers={"User-Agent": _WEB_HEADERS["User-Agent"]},
                timeout=_SOURCE_TIMEOUT_SECONDS,
            )
            response.encoding = "gbk"
            response.raise_for_status()
            return _stock_search_item_from_tencent_quote(symbol, response.text)

        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:
            logger.warning("market: tencent stock search quote for {} failed: {}", symbol, exc)
            return None

    async def fetch_headlines(self, symbol: str | None = None) -> list[NewsItem]:
        if not symbol:
            return []
        rows = await self._records(lambda ak: ak.stock_news_em(symbol=symbol))
        return [self._to_news(row, tags=["个股"], symbols=[symbol]) for row in rows[:20]]

    async def fetch_news(self, category: str | None = None) -> list[NewsItem]:
        cls_rows, eastmoney_rows, tonghuashun_rows, yicai_rows, xueqiu_rows = await asyncio.gather(
            self._fetch_news_source_best_effort("cls.telegraph", self._fetch_cls_telegraph_rows),
            self._fetch_news_source_best_effort("eastmoney.global", self._fetch_eastmoney_news_rows),
            self._fetch_news_source_best_effort("tonghuashun.global", self._fetch_tonghuashun_news_rows),
            self._fetch_news_source_best_effort("yicai.global", self._fetch_yicai_news_rows),
            self._fetch_news_source_best_effort("xueqiu.livenews", self._fetch_xueqiu_news_rows),
        )
        tags = [category or "综合", "精选"]
        items: list[NewsItem] = []
        # 财联社 is chronological → newest first. 东方财富 / 同花顺 / 第一财经 are ranked
        # news hotlists, so their upstream (rank) order is preserved.
        items.extend(self._news_from_rows(cls_rows, tags, sort_by_time=True))
        items.extend(self._news_from_rows(eastmoney_rows, tags, sort_by_time=False))
        items.extend(self._news_from_rows(tonghuashun_rows, tags, sort_by_time=False))
        items.extend(self._news_from_rows(yicai_rows, tags, sort_by_time=False))
        # 雪球 is a heat-ranked 资讯 feed (no publish time). Tag rows "精选" only —
        # no 综合 — so each row shows just 热度 / 精选 / 雪球; keep the rank order.
        items.extend(self._news_from_rows(xueqiu_rows, ["精选"], sort_by_time=False))
        return items

    async def fetch_ai_hotspots(self) -> list[NewsItem]:
        """Smart finance hotlist mirroring quicktiny's news-hotlist 财经热点.

        The upstream page builds this client-side: fetch eight ranked feeds,
        merge similar titles, keep only finance-related generic hot searches,
        then rank by source weight plus upstream rank. We do the same server-side
        so the frontend gets a stable list instead of keyword-filtering 7x24.
        """

        (
            douyin_rows,
            weibo_rows,
            baidu_rows,
            toutiao_rows,
            eastmoney_rows,
            ths_rows,
            sina_rows,
            yicai_rows,
        ) = await asyncio.gather(
            self._fetch_news_source_best_effort(
                "quicktiny.douyin",
                lambda: self._fetch_quicktiny_generic_news_rows(_QUICKTINY_DOUYIN_URL, "抖音", "douyin"),
            ),
            self._fetch_news_source_best_effort(
                "quicktiny.weibo",
                lambda: self._fetch_quicktiny_generic_news_rows(_QUICKTINY_WEIBO_URL, "微博", "weibo"),
            ),
            self._fetch_news_source_best_effort(
                "quicktiny.baidu",
                lambda: self._fetch_quicktiny_generic_news_rows(_QUICKTINY_BAIDU_URL, "百度", "baidu"),
            ),
            self._fetch_news_source_best_effort(
                "quicktiny.toutiao",
                lambda: self._fetch_quicktiny_generic_news_rows(_QUICKTINY_TOUTIAO_URL, "今日头条", "toutiao"),
            ),
            self._fetch_news_source_best_effort("quicktiny.eastmoney", self._fetch_eastmoney_news_rows),
            self._fetch_news_source_best_effort("quicktiny.ths", self._fetch_tonghuashun_quicktiny_rows),
            self._fetch_news_source_best_effort(
                "quicktiny.sina",
                lambda: self._fetch_quicktiny_generic_news_rows(_QUICKTINY_SINA_URL, "新浪财经", "sina"),
            ),
            self._fetch_news_source_best_effort("quicktiny.yicai", self._fetch_yicai_news_rows),
        )

        return _build_finance_hotspots([
            ("eastmoney", "东方财富", eastmoney_rows, False),
            ("ths", "同花顺", ths_rows, False),
            ("sina", "新浪财经", sina_rows, False),
            ("yicai", "第一财经", yicai_rows, False),
            ("douyin", "抖音", douyin_rows, True),
            ("weibo", "微博", weibo_rows, True),
            ("baidu", "百度", baidu_rows, True),
            ("toutiao", "今日头条", toutiao_rows, True),
        ])

    def _news_from_rows(
        self,
        rows: list[dict[str, Any]],
        tags: list[str],
        *,
        sort_by_time: bool,
    ) -> list[NewsItem]:
        normalized = [
            {
                **row,
                "标题": row.get("标题") or row.get("title") or row.get("content") or row.get("brief") or "财联社电报",
                "内容": row.get("内容") or row.get("content") or row.get("brief") or "",
                "摘要": row.get("摘要") or row.get("brief") or row.get("content") or "",
                "来源": row.get("来源") or row.get("source") or "财联社",
                "链接": row.get("链接") or row.get("url") or _CLS_TELEGRAPH_URL,
                "发布时间": row.get("发布时间") or row.get("ctime"),
            }
            for row in rows
        ]
        if sort_by_time:
            normalized.sort(key=lambda row: _now_from(row) or _now(), reverse=True)
        return [
            self._to_news(
                row,
                tags=_merge_unique(tags, _news_tags_from_row(row)),
                symbols=_news_symbols_from_row(row),
            )
            for row in normalized[:_NEWS_ITEMS_PER_SOURCE]
        ]

    async def fetch_flash(self) -> list[FlashItem]:
        # 7x24 快讯 aggregates two round-the-clock live wires: 财联社电报 and
        # 华尔街见闻. Each is best-effort so one outage never blanks the feed.
        cls_rows, wscn_rows = await asyncio.gather(
            self._fetch_news_source_best_effort("cls.telegraph.flash", self._fetch_cls_telegraph_rows),
            self._fetch_news_source_best_effort("wallstreetcn.lives", self._fetch_wallstreetcn_flash_rows),
        )
        items = self._flash_from_rows(cls_rows, source="财联社")
        items.extend(self._flash_from_rows(wscn_rows, source="华尔街见闻"))
        # Interleave both wires newest-first so the merged tab reads chronologically.
        items.sort(key=lambda item: item.published_at, reverse=True)
        return items

    def _flash_from_rows(self, rows: list[dict[str, Any]], *, source: str) -> list[FlashItem]:
        now = _now()
        items: list[FlashItem] = []
        for row in rows[:_FLASH_ITEMS_PER_SOURCE]:
            content = str(_col(row, "内容", "摘要", "标题", "content", "title", default="")).strip()
            if not content:
                continue
            title = str(_col(row, "标题", "title", default="")).strip()
            items.append(
                FlashItem(
                    id=_stable_id("flash", source, content),
                    content=content,
                    title=title,
                    source=source,
                    url=self._normalize_url(str(_col(row, "链接", "url", default=""))),
                    level=FlashLevel.normal,
                    symbols=[],
                    published_at=_now_from(row) or now,
                )
            )
        return items

    async def _fetch_wallstreetcn_flash_rows(self) -> list[dict[str, Any]]:
        """华尔街见闻 7x24 快讯 — the public global live feed (content/lives)."""

        def _run() -> list[dict[str, Any]]:
            import requests

            response = requests.get(
                _WSCN_LIVES_URL,
                params={"channel": "global-channel", "limit": _WSCN_FLASH_LIMIT, "accept": "live"},
                headers={"User-Agent": _WEB_HEADERS["User-Agent"]},
                timeout=_SOURCE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data")
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                items = []
            rows: list[dict[str, Any]] = []
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                content = str(entry.get("content_text") or "").strip()
                if not content:
                    continue
                rows.append({
                    "标题": str(entry.get("title") or "").strip(),
                    "内容": content,
                    "摘要": content,
                    "来源": "华尔街见闻",
                    "链接": str(entry.get("uri") or "").strip(),
                    # display_time is unix seconds — _now_from's fallback handles it.
                    "发布时间": entry.get("display_time"),
                })
            return rows

        return await asyncio.to_thread(_run)

    # ---- helpers -----------------------------------------------------------

    def _to_news(self, row: dict[str, Any], *, tags: list[str], symbols: list[str]) -> NewsItem:
        title = str(_col(row, "标题", "新闻标题", "title"))
        source = str(_col(row, "来源", "文章来源", "source", default="akshare"))
        url = self._normalize_url(str(_col(row, "链接", "新闻链接", "url", default="")))
        return NewsItem(
            # Include source + url so the same headline surfaced by two upstreams
            # (e.g. 财联社 and 东方财富) yields distinct ids — a title-only hash
            # collides and breaks React keys downstream.
            id=_stable_id("news", source, url, title),
            title=title,
            summary=str(_col(row, "内容", "摘要", "summary", default="")),
            source=source,
            url=url,
            tags=tags,
            symbols=symbols,
            sentiment=None,
            heat=_to_optional_int(_col(row, "热度", "heat", default=None)),
            views=_to_optional_int(_col(row, "观看量", "views", default=None)),
            published_at=_resolve_published_at(row),
        )

    def _normalize_url(self, value: str) -> str:
        raw = value.strip()
        if not raw:
            return ""
        if raw.startswith("//"):
            return f"https:{raw}"
        if raw.startswith("https:https://"):
            return raw.replace("https:https://", "https://", 1)
        if raw.startswith("http:http://"):
            return raw.replace("http:http://", "http://", 1)
        return raw

    async def _records(self, call: Any) -> list[dict[str, Any]]:
        """Run a blocking akshare call in a thread and return list-of-dicts."""

        def _run() -> list[dict[str, Any]]:
            import akshare as ak

            frame = call(ak)
            return list(frame.to_dict(orient="records"))

        return await asyncio.to_thread(_run)

    async def _fetch_cls_telegraph_rows(self) -> list[dict[str, Any]]:
        """Read 财联社电报 directly from cls.cn's current cache API."""

        def _run() -> list[dict[str, Any]]:
            import requests

            response = requests.get(
                _CLS_CACHE_URL,
                params={
                    "rn": 30,
                    "name": "telegraph",
                },
                headers=_WEB_HEADERS,
                timeout=_SOURCE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("errno") != 0:
                raise RuntimeError(f"cls telegraph errno={payload.get('errno')}")
            data = payload.get("data") or {}
            rows = data.get("roll_data") or []
            if not isinstance(rows, list):
                raise TypeError("cls telegraph roll_data missing")
            return [self._normalize_cls_row(row) for row in rows if isinstance(row, dict)]

        return await asyncio.to_thread(_run)

    async def _fetch_eastmoney_news_rows(self) -> list[dict[str, Any]]:
        """东方财富资讯热榜 — finance.eastmoney.com articles ranked by click/hot.

        East Money publishes no stable public article-heat API, so this mirrors the
        stock.quicktiny.cn/news-hotlist page by proxying its aggregator endpoint,
        which returns 东方财富 articles already ordered by rank (rank 1..N). Rows are
        kept in that order — fetch_news leaves 东方财富 unsorted so the rank shows
        through. Third-party dependency; ``_fetch_news_source_best_effort`` degrades
        it to empty if the aggregator is down.
        """

        def _run() -> list[dict[str, Any]]:
            import requests

            response = requests.get(
                _QUICKTINY_EASTMONEY_URL,
                params={"limit": _EASTMONEY_NEWS_LIMIT},
                headers={
                    "User-Agent": _WEB_HEADERS["User-Agent"],
                    "Referer": _QUICKTINY_NEWS_REFERER,
                },
                timeout=_SOURCE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success"):
                raise RuntimeError(f"quicktiny eastmoney success={payload.get('success')}")
            data = payload.get("data")
            if not isinstance(data, list):
                data = []
            rows: list[dict[str, Any]] = []
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                title = str(entry.get("title") or "").strip()
                if not title:
                    continue
                summary = str(entry.get("summary") or "")
                category = str(entry.get("category") or "").strip()
                rows.append({
                    "标题": title,
                    "摘要": summary,
                    "内容": summary,
                    # Must be 东方财富 so the frontend routes it to that tab; the
                    # article's original publisher lives in `entry["source"]`.
                    "来源": "东方财富",
                    "链接": str(entry.get("url") or "").strip() or _EASTMONEY_HOME_URL,
                    "发布时间": entry.get("publishTime"),
                    "热度": entry.get("hotValue"),
                    "观看量": entry.get("clickNum"),
                    "分类": category,
                    "标签": _merge_unique(
                        [category] if category else [],
                        entry.get("tags") if isinstance(entry.get("tags"), list) else [],
                    ),
                })
            return rows

        return await asyncio.to_thread(_run)

    async def _fetch_tonghuashun_news_rows(self) -> list[dict[str, Any]]:
        rows = await self._fetch_tonghuashun_quicktiny_rows()
        if rows:
            return rows
        rows = await self._fetch_tonghuashun_rank_rows()
        if rows:
            return rows
        return await self._fetch_tonghuashun_realtime_rows()

    async def _fetch_tonghuashun_quicktiny_rows(self) -> list[dict[str, Any]]:
        """同花顺财经热点榜 — same /news/ths feed used by quicktiny/news-hotlist."""

        def _run() -> list[dict[str, Any]]:
            import requests

            response = requests.get(
                _QUICKTINY_THS_URL,
                params={"limit": _TONGHUASHUN_NEWS_RANK_LIMIT},
                headers={
                    "User-Agent": _WEB_HEADERS["User-Agent"],
                    "Referer": _QUICKTINY_NEWS_REFERER,
                },
                timeout=_SOURCE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success"):
                raise RuntimeError(f"quicktiny ths success={payload.get('success')}")
            data = payload.get("data")
            if not isinstance(data, list):
                data = []
            rows: list[dict[str, Any]] = []
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                title = str(entry.get("title") or "").strip()
                if not title:
                    continue
                summary = _quicktiny_ths_summary(entry)
                category = str(entry.get("category") or "").strip()
                entry_type = str(entry.get("type") or "").strip()
                stocks = entry.get("stocks") if isinstance(entry.get("stocks"), list) else []
                published_at = _tonghuashun_entry_publish_time(entry)
                rows.append({
                    "标题": title,
                    "摘要": summary,
                    "内容": summary,
                    "来源": "同花顺",
                    "链接": _normalize_external_url(str(entry.get("url") or "").strip(), _TONGHUASHUN_NEWS_HOME_URL),
                    "发布时间": published_at,
                    "热度": entry.get("hotValue"),
                    "分类": category,
                    "标签": _merge_unique(
                        [category, entry_type],
                        [str(stock.get("name") or "").strip() for stock in stocks if isinstance(stock, dict)],
                    ),
                    "股票": [
                        str(stock.get("code") or "").strip()
                        for stock in stocks
                        if isinstance(stock, dict) and str(stock.get("code") or "").strip()
                    ],
                })
            return rows

        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:
            logger.warning("market: quicktiny ths news unavailable: {}", exc)
            return []

    async def _fetch_tonghuashun_rank_rows(self) -> list[dict[str, Any]]:
        """同花顺新闻热点榜 — news.10jqka.com.cn right-rail TOP/日排行."""

        def _run() -> list[dict[str, Any]]:
            import requests

            response = requests.get(
                _TONGHUASHUN_NEWS_HOME_URL,
                headers={
                    "User-Agent": _WEB_HEADERS["User-Agent"],
                    "Referer": _TONGHUASHUN_NEWS_HOME_URL,
                },
                timeout=_SOURCE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "gbk"
            rows = _parse_tonghuashun_rank_rows(response.text)
            if not rows:
                raise RuntimeError("tonghuashun zxrank missing")
            return rows[:_TONGHUASHUN_NEWS_RANK_LIMIT]

        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:
            logger.warning("market: tonghuashun homepage rank unavailable: {}", exc)
            return []

    async def _fetch_quicktiny_generic_news_rows(
        self,
        url: str,
        source: str,
        platform: str,
    ) -> list[dict[str, Any]]:
        """Read one quicktiny news-hotlist source and normalize its common fields."""

        def _run() -> list[dict[str, Any]]:
            import requests

            response = requests.get(
                url,
                params={"limit": _AI_HOTSPOT_SOURCE_LIMIT},
                headers={
                    "User-Agent": _WEB_HEADERS["User-Agent"],
                    "Referer": _QUICKTINY_NEWS_REFERER,
                },
                timeout=_SOURCE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success"):
                raise RuntimeError(f"quicktiny {platform} success={payload.get('success')}")
            data = payload.get("data")
            if not isinstance(data, list):
                data = []
            rows: list[dict[str, Any]] = []
            for index, entry in enumerate(data):
                if not isinstance(entry, dict):
                    continue
                title = str(entry.get("title") or "").strip()
                if not title:
                    continue
                summary = str(entry.get("summary") or entry.get("description") or entry.get("desc") or "").strip()
                tags = _merge_unique(
                    entry.get("category"),
                    entry.get("tags") if isinstance(entry.get("tags"), list) else [],
                    source,
                )
                rows.append({
                    "标题": title,
                    "摘要": summary,
                    "内容": summary,
                    "来源": source,
                    "链接": _normalize_external_url(str(entry.get("url") or "").strip()),
                    "发布时间": entry.get("publishTime"),
                    "热度": entry.get("rawHotValue") or entry.get("hotValue"),
                    "观看量": entry.get("viewCount") or entry.get("discussCount"),
                    "分类": entry.get("category"),
                    "标签": tags,
                    "平台": platform,
                    "排名": entry.get("rank") or index + 1,
                })
            return rows

        return await asyncio.to_thread(_run)

    async def _fetch_yicai_news_rows(self) -> list[dict[str, Any]]:
        """第一财经资讯热榜 — same /news/yicai feed used by quicktiny/news-hotlist."""

        def _run() -> list[dict[str, Any]]:
            import requests

            response = requests.get(
                _QUICKTINY_YICAI_URL,
                params={"limit": _YICAI_NEWS_LIMIT},
                headers={
                    "User-Agent": _WEB_HEADERS["User-Agent"],
                    "Referer": _QUICKTINY_NEWS_REFERER,
                },
                timeout=_SOURCE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success"):
                raise RuntimeError(f"quicktiny yicai success={payload.get('success')}")
            data = payload.get("data")
            if not isinstance(data, list):
                data = []
            rows: list[dict[str, Any]] = []
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                title = str(entry.get("title") or "").strip()
                if not title:
                    continue
                category = str(entry.get("category") or "").strip()
                tags = [category]
                if entry.get("isVideo"):
                    tags.append("视频")
                if entry.get("isLive"):
                    tags.append("直播")
                rows.append({
                    "标题": title,
                    "摘要": str(entry.get("summary") or "").strip(),
                    "内容": str(entry.get("summary") or "").strip(),
                    "来源": "第一财经",
                    "链接": _normalize_external_url(str(entry.get("url") or "").strip(), "https://www.yicai.com/"),
                    "发布时间": entry.get("publishTime"),
                    "热度": entry.get("hotValue"),
                    "分类": category,
                    "标签": tags,
                })
            return rows

        return await asyncio.to_thread(_run)

    async def _fetch_xueqiu_news_rows(self) -> list[dict[str, Any]]:
        """雪球资讯热榜 — xueqiu.com/today 今日话题 hot events (hot_event/tag.json).

        A heat-ranked topic feed: each entry carries a title, a summary and its
        热度值, but no publish time. The API host rejects tokenless calls, so a
        homepage GET first seeds the anonymous ``u`` cookie. Best-effort: degrades
        to empty if xueqiu is unreachable (same as every other news source).
        """

        def _run() -> list[dict[str, Any]]:
            import requests

            session = requests.Session()
            session.headers.update({
                "User-Agent": _WEB_HEADERS["User-Agent"],
                "Referer": _XUEQIU_HOME_URL,
            })
            # Seed the anonymous cookie the hot_event endpoint checks for.
            session.get(_XUEQIU_COOKIE_SEED_URL, timeout=_SOURCE_TIMEOUT_SECONDS)
            response = session.get(_XUEQIU_HOT_EVENT_URL, timeout=_SOURCE_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success"):
                raise RuntimeError(f"xueqiu hot_event success={payload.get('success')}")
            data = payload.get("data")
            if not isinstance(data, list):
                data = []
            rows: list[dict[str, Any]] = []
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                # Topic titles arrive wrapped in hashes ("#端侧AI概念…#"); unwrap them.
                title = str(entry.get("title") or "").strip().strip("#").strip()
                if not title:
                    continue
                content = str(entry.get("content") or "").strip()
                rows.append({
                    "标题": title,
                    "摘要": content,
                    "内容": content,
                    "来源": "雪球",
                    "链接": _normalize_external_url(str(entry.get("url") or "").strip(), _XUEQIU_HOME_URL),
                    # Heat ranking carries no publish time — leave it unset so the
                    # UI shows no timestamp rather than a fabricated/"--" one.
                    "发布时间": None,
                    # reason is "热度值 170.8万" — _to_optional_int unwraps 万/亿.
                    "热度": entry.get("reason"),
                })
            return rows[:_XUEQIU_NEWS_LIMIT]

        return await asyncio.to_thread(_run)

    async def _fetch_tonghuashun_realtime_rows(self) -> list[dict[str, Any]]:
        rows = await self._records(lambda ak: ak.stock_info_global_ths())
        return [
            {
                "标题": row.get("标题") or "同花顺快讯",
                "摘要": row.get("内容") or "",
                "内容": row.get("内容") or "",
                "来源": "同花顺",
                "链接": row.get("链接") or _TONGHUASHUN_REALTIME_URL,
                "发布时间": row.get("发布时间"),
            }
            for row in rows[:20]
        ]

    async def _fetch_news_source_best_effort(
        self,
        source_name: str,
        fetcher: Any,
    ) -> list[dict[str, Any]]:
        try:
            return await asyncio.wait_for(fetcher(), timeout=_SOURCE_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("market: news source {} unavailable: {}", source_name, exc)
            return []

    def _normalize_cls_row(self, row: dict[str, Any]) -> dict[str, Any]:
        timestamp = row.get("ctime")
        title = str(row.get("title") or "").strip()
        content = str(row.get("content") or row.get("brief") or title).strip()
        article_id = row.get("id")
        article_url = f"https://www.cls.cn/detail/{article_id}" if article_id else _CLS_TELEGRAPH_URL
        published_at = _from_unix_seconds(timestamp) or _now()
        return {
            "标题": title or content or "财联社电报",
            "内容": content,
            "摘要": str(row.get("brief") or content),
            "来源": "财联社",
            "链接": article_url,
            "发布时间": published_at.isoformat(),
        }

    async def _safe_records(self, source_name: str, call: Any) -> list[dict[str, Any]]:
        try:
            return await asyncio.wait_for(self._records(call), timeout=_SOURCE_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("market: hotlist source {} failed: {}", source_name, exc)
            return []

    # ---- 所属板块 / 行业 enrichment ----------------------------------------

    async def _enrich_concepts(self, items: list[HotItem]) -> None:
        """Fill any still-blank ``concept`` with the stock's industry board.

        Most items already carry ``所属行业`` from the 同花顺 rows; this only
        covers the leftovers (e.g. Eastmoney-only names) via a per-symbol lookup.
        Bounded concurrency + a day-long cache keep it cheap, and it degrades to a
        no-op when every item is already labelled.
        """
        missing = [item for item in items if not item.concept]
        if not missing:
            return
        sem = asyncio.Semaphore(_SECTOR_CONCURRENCY)

        async def one(item: HotItem) -> None:
            async with sem:
                industry = await self._industry_for(item.symbol)
            if industry:
                item.concept = industry

        await asyncio.gather(*(one(item) for item in missing))

    async def _industry_for(self, symbol: str) -> str:
        cached = self._sector_cache.get(symbol)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0]
        try:
            rows = await asyncio.wait_for(
                self._records(lambda ak: ak.stock_individual_info_em(symbol=symbol)),
                timeout=_SECTOR_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            # A slow/failed upstream (incl. the wait_for timeout) must never stall
            # the whole hotlist refresh: fall back to any stale cached value, else
            # leave the concept blank.
            logger.warning("market: industry lookup for {} failed: {}", symbol, exc)
            return cached[0] if cached else ""
        industry = ""
        for row in rows:
            if str(_col(row, "item", "指标")) == "行业":
                industry = str(_col(row, "value", "值", default="")).strip()
                break
        # Cache even an empty result so a symbol with no industry isn't refetched
        # every cycle; a real value simply overwrites it next time it expires.
        self._sector_cache[symbol] = (industry, time.monotonic() + _SECTOR_TTL_SECONDS)
        return industry


def _build_stock_search_results(rows: list[dict[str, Any]], query: str, limit: int) -> list[StockSearchItem]:
    now = _now()
    ranked: list[tuple[int, StockSearchItem]] = []
    seen: set[str] = set()

    for row in rows:
        symbol = _normalize_symbol(_col(row, "代码", "股票代码", "symbol", "code", default=""))
        name = str(_col(row, "名称", "股票名称", "name", default=symbol)).strip()
        if not symbol or not name or symbol in seen:
            continue
        rank = _stock_search_rank(symbol, name, query)
        if rank is None:
            continue
        seen.add(symbol)
        ranked.append(
            (
                rank,
                StockSearchItem(
                    symbol=symbol,
                    name=name,
                    market=_market_for_symbol(symbol),
                    latest_price=_finite_optional_float(_col(row, "最新价", "现价", "price", default=None)),
                    change_pct=_finite_optional_float(_col(row, "涨跌幅", "change_pct", default=None)),
                    concept=str(_col(row, "所属行业", "行业", "concept", default="")).strip(),
                    source="东方财富",
                    updated_at=now,
                ),
            )
        )

    ranked.sort(key=lambda pair: (pair[0], pair[1].symbol))
    return [item for _rank, item in ranked[:limit]]


def _build_stock_pool_results(rows: list[dict[str, Any]], *, source: str = "东方财富股票池") -> list[StockSearchItem]:
    now = _now()
    items: list[StockSearchItem] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        symbol = _normalize_symbol(_col(row, "代码", "股票代码", "symbol", "code", default=""))
        name = str(_col(row, "名称", "股票名称", "name", default=symbol)).strip()
        if not symbol or not name:
            continue
        market = _market_for_symbol(symbol)
        key = (market, symbol)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            StockSearchItem(
                symbol=symbol,
                name=name,
                market=market,
                latest_price=None,
                change_pct=None,
                concept=str(_col(row, "所属行业", "行业", "concept", default="")).strip(),
                source=source,
                updated_at=now,
            )
        )
    items.sort(key=lambda item: item.symbol)
    return items


def _stock_search_item_from_tencent_quote(symbol: str, text: str) -> StockSearchItem | None:
    for line in text.strip().splitlines():
        parts = line.split("~")
        if len(parts) < 33 or parts[2] != symbol or not parts[1]:
            continue
        return StockSearchItem(
            symbol=symbol,
            name=parts[1],
            market=_market_for_symbol(symbol),
            latest_price=_finite_optional_float(parts[3]),
            change_pct=_finite_optional_float(parts[32]),
            concept="",
            source="腾讯行情",
            updated_at=_now(),
        )
    return None


def _stock_search_rank(symbol: str, name: str, query: str) -> int | None:
    keyword = query.strip().lower()
    digits = "".join(char for char in keyword if char.isdigit())
    symbol_lower = symbol.lower()
    name_lower = name.lower()

    if not keyword:
        return None
    if keyword == symbol_lower or (digits and digits == symbol):
        return 0
    if digits and symbol.startswith(digits):
        return 1
    if keyword == name_lower:
        return 2
    if name_lower.startswith(keyword):
        return 3
    if digits and digits in symbol:
        return 4
    if keyword in symbol_lower or keyword in name_lower:
        return 5
    return None


def _tencent_symbol(symbol: str) -> str:
    if symbol.startswith("6"):
        return f"sh{symbol}"
    if symbol[:1] in ("4", "8") or symbol.startswith("92"):
        return f"bj{symbol}"
    return f"sz{symbol}"


def _stock_matches_query(symbol: str, name: str, query: str) -> bool:
    return _stock_search_rank(symbol, name, query) is not None


def _market_for_symbol(symbol: str) -> str:
    if symbol.startswith("6"):
        return "沪市A股"
    if symbol.startswith(("0", "3")):
        return "深市A股"
    if symbol.startswith(("4", "8", "92")):
        return "北交所"
    return "A股"


def _finite_optional_float(value: Any) -> float | None:
    parsed = _to_optional_float(value)
    if parsed is not None and (parsed != parsed or parsed in (float("inf"), float("-inf"))):
        return None
    return parsed


def _build_finance_hotspots(
    sources: list[tuple[str, str, list[dict[str, Any]], bool]],
) -> list[NewsItem]:
    merged: list[dict[str, Any]] = []

    for platform, source_name, rows, require_finance_match in sources:
        for index, row in enumerate(rows):
            title = str(_col(row, "标题", "title", default="")).strip()
            if not title:
                continue
            summary = str(_col(row, "摘要", "内容", "summary", "description", default="")).strip()
            if require_finance_match and not _is_finance_hotspot_text(title, summary):
                continue

            score = _quicktiny_source_score(index, platform)
            match = _find_similar_hotspot(merged, title)
            if match is None:
                heat = _to_optional_int(_col(row, "热度", "hotValue", "rawHotValue", default=None))
                merged.append({
                    "title": title,
                    "summary": summary,
                    "url": _normalize_external_url(str(_col(row, "链接", "url", default="")).strip()),
                    "score": score,
                    "representative_score": score,
                    "platforms": [platform],
                    "source_names": [source_name],
                    "tags": _merge_unique("财经热点", source_name, _news_tags_from_row(row)),
                    "symbols": _news_symbols_from_row(row),
                    "heat": heat,
                    "published_at": _resolve_published_at(row),
                })
                continue

            match["score"] += score
            match["platforms"] = _merge_unique(match["platforms"], [platform])
            match["source_names"] = _merge_unique(match["source_names"], [source_name])
            match["tags"] = _merge_unique(match["tags"], source_name, _news_tags_from_row(row))
            match["symbols"] = _merge_unique(match["symbols"], _news_symbols_from_row(row))
            row_heat = _to_optional_int(_col(row, "热度", "hotValue", "rawHotValue", default=None))
            current_heat = match.get("heat")
            if row_heat is not None and (current_heat is None or row_heat > current_heat):
                match["heat"] = row_heat
            row_published_at = _resolve_published_at(row)
            current_published_at = match.get("published_at")
            if row_published_at is not None and (
                current_published_at is None or row_published_at > current_published_at
            ):
                match["published_at"] = row_published_at
            if score > match["representative_score"]:
                match["representative_score"] = score
                match["title"] = title
                match["summary"] = summary
                match["url"] = _normalize_external_url(str(_col(row, "链接", "url", default="")).strip())

    merged.sort(key=lambda item: float(item["score"]), reverse=True)
    result: list[NewsItem] = []
    for index, item in enumerate(merged[:_AI_HOTSPOT_RESULT_LIMIT], start=1):
        platforms = [str(value) for value in item["platforms"]]
        source_names = [str(value) for value in item["source_names"]]
        result.append(
            NewsItem(
                id=_stable_id("ai-hotspot", str(item["title"]), str(item["url"]), ",".join(platforms)),
                title=str(item["title"]),
                summary=str(item["summary"]),
                source="AI智能热榜",
                url=str(item["url"]),
                tags=_merge_unique("财经热点", source_names, [f"综合排名 {index}"]),
                symbols=[str(symbol) for symbol in item["symbols"]],
                sentiment=None,
                heat=item["heat"],
                views=int(float(item["score"])),
                published_at=item["published_at"],
            )
        )
    return result


def _quicktiny_source_score(index: int, platform: str) -> int:
    weight = _SMART_SOURCE_WEIGHTS.get(platform, 5)
    return weight * 5 + max(0, 100 - index * 2)


def _find_similar_hotspot(items: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    for item in items:
        if _titles_match(str(item["title"]), title):
            return item
    return None


def _titles_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    normalized_left = _normalize_title_for_match(left)
    normalized_right = _normalize_title_for_match(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left in normalized_right or normalized_right in normalized_left:
        return True
    return _levenshtein_similarity(normalized_left, normalized_right) > 0.7


def _normalize_title_for_match(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum() or "\u4e00" <= char <= "\u9fff")


def _levenshtein_similarity(left: str, right: str) -> float:
    max_length = max(len(left), len(right))
    if max_length == 0:
        return 1.0
    distance = _levenshtein_distance(left, right)
    return (max_length - distance) / max_length


def _levenshtein_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            if left_char == right_char:
                current.append(previous[j - 1])
            else:
                current.append(min(previous[j - 1] + 1, current[j - 1] + 1, previous[j] + 1))
        previous = current
    return previous[-1]


def _is_finance_hotspot_text(title: str, summary: str) -> bool:
    haystack = f"{title} {summary}"
    return any(keyword in haystack for keyword in _FINANCE_HOTSPOT_KEYWORDS)


def _resolve_published_at(row: dict[str, Any]) -> datetime | None:
    """Publish time for a news row, or None when the source carries none.

    A heat-ranked feed (雪球 hot topics) is ordered by popularity, not time, so it
    has no timestamp to show — don't fabricate one. Only fall back to "now" when a
    timestamp was present but couldn't be parsed.
    """
    parsed = _now_from(row)
    if parsed is not None:
        return parsed
    raw = _col(row, "发布时间", "时间", "date", default=None)
    return None if raw in (None, "") else _now()


def _now_from(row: dict[str, Any]) -> datetime | None:
    raw = _col(row, "发布时间", "时间", "date", default=None)
    if not raw:
        return None
    raw_text = str(raw).strip()
    try:
        parsed = datetime.fromisoformat(raw_text.replace("Z", "+00:00") if raw_text.endswith("Z") else raw_text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=_CN_TZ).astimezone(UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y, %I:%M:%S %p",):
        try:
            return datetime.strptime(raw_text, fmt).replace(tzinfo=_CN_TZ).astimezone(UTC)
        except ValueError:
            continue
    return _from_unix_seconds(raw)


def _from_unix_seconds(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _normalize_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    if raw.startswith(("SZ", "SH", "BJ")) and len(raw) > 2:
        return raw[2:]
    return raw


def _to_float(value: Any) -> float:
    try:
        return float(str(value).replace("%", "").strip() or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _to_optional_float(value: Any) -> float | None:
    if value in (None, "", "--"):
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _to_optional_int(value: Any) -> int | None:
    if value in (None, "", "--"):
        return None
    text = str(value).replace(",", "").strip()
    multiplier = 1
    if "亿" in text:
        multiplier = 100_000_000
    elif "万" in text:
        multiplier = 10_000
    number = "".join(char for char in text if char.isdigit() or char == ".")
    if number:
        try:
            return int(float(number) * multiplier)
        except (TypeError, ValueError):
            return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value).strip() or 0))
    except (TypeError, ValueError):
        return 0


def min_non_null(current: int | None, candidate: int | None) -> int | None:
    if candidate is None:
        return current
    if current is None:
        return candidate
    return min(current, candidate)


def merge_reason(current: str, incoming: str) -> str:
    if not current:
        return incoming
    if incoming in current:
        return current
    return f"{current} / {incoming}"
