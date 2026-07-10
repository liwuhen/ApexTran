"""Live A-share hotlist via official 24h 热榜 endpoints (no akshare wrapper).

akshare's Eastmoney calls hit ``push2.eastmoney.com``, which refuses this host
(``RemoteDisconnected``), and its 同花顺 helpers are 技术选股 (连续上涨…), not a
popularity ranking. So the hotlist is built directly from the endpoints the two
sites' own pages use — all reachable here — plus Tencent for authoritative
names/quotes:

- **同花顺日榜** (24h 热榜): name, code, 日涨跌幅, rank, and 概念标签 in one call.
- **东方财富人气榜**: ranked ``secid`` list (App API ``emappdata``, which — unlike
  push2 — is not blocked).
- **腾讯行情** (``qt.gtimg.cn``): fills name / change / price, covering symbols that
  are on the Eastmoney board but not the 同花顺 one.

Each source is best-effort: if one is down the others still yield a hotlist.
News/flash keep using the akshare source (delegated).
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger

from ..domain.models import FlashItem, HotItem, NewsItem, StockSearchItem
from .akshare_source import AkshareMarketSource

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_THS_URL = "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock"
_EM_RANK_URL = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
_TX_QUOTE_URL = "https://qt.gtimg.cn/q="
_TIMEOUT = 10.0
_TOP_N = 60
_TX_CHUNK = 60
# 同花顺热榜「大家都在看」= real-time heat (type=hour); "day" is the full-day
# accumulation. list_type must be "normal" — other values return an empty list.
_THS_TYPE = "hour"


class LiveMarketSource:
    """Builds the hotlist from live 同花顺 + 东方财富 + 腾讯 endpoints."""

    def __init__(self) -> None:
        # News / flash / headlines are unrelated to the hotlist rework — delegate
        # them to the existing akshare source so nothing there regresses.
        self._news = AkshareMarketSource()

    async def fetch_hotlist(self) -> list[HotItem]:
        async with httpx.AsyncClient(headers={"User-Agent": _UA}, timeout=_TIMEOUT) as client:
            ths, em = await asyncio.gather(self._ths_hot(client), self._em_hot(client))
            codes = sorted(set(ths) | set(em))
            quotes = await self._tencent_quotes(client, codes)
        return self._merge(ths, em, quotes)

    async def search_stocks(self, query: str, limit: int = 20) -> list[StockSearchItem]:
        return await self._news.search_stocks(query, limit)

    async def list_stock_instruments(self) -> list[StockSearchItem]:
        return await self._news.list_stock_instruments()

    async def fetch_headlines(self, symbol: str | None = None) -> list[NewsItem]:
        return await self._news.fetch_headlines(symbol)

    async def fetch_news(self, category: str | None = None) -> list[NewsItem]:
        return await self._news.fetch_news(category)

    async def fetch_ai_hotspots(self) -> list[NewsItem]:
        return await self._news.fetch_ai_hotspots()

    async def fetch_flash(self) -> list[FlashItem]:
        return await self._news.fetch_flash()

    # ---- sources -----------------------------------------------------------

    async def _ths_hot(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        """同花顺 24h 热榜 → {code: {name, change_pct, concept, ths_rank, popularity}}."""
        try:
            resp = await client.get(
                _THS_URL,
                params={"stock_type": "a", "type": _THS_TYPE, "list_type": "normal"},
                headers={"Referer": "https://dq.10jqka.com.cn/"},
            )
            resp.raise_for_status()
            rows = resp.json()["data"]["stock_list"]
        except Exception as exc:
            logger.warning("market: 同花顺 hot list failed: {}", exc)
            return {}
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            code = str(row.get("code", "")).strip()
            if not code:
                continue
            tag = row.get("tag") or {}
            concept_tags = [str(t) for t in (tag.get("concept_tag") or []) if t]
            # popularity_tag is either a 连板 label ("4天3板"/"2连板"/"首板") or a
            # popularity note ("持续上榜"). Surface the 连板 one at the head of the
            # concept column and parse its board count.
            popularity = str(tag.get("popularity_tag") or "").strip()
            concept_parts = concept_tags[:3]
            boards = 0
            if "板" in popularity:
                boards = _parse_boards(popularity)
                concept_parts = [popularity, *concept_parts]
            out[code] = {
                "name": str(row.get("name", "")).strip(),
                "change_pct": _to_float(row.get("rise_and_fall")),
                "concept": " · ".join(concept_parts),
                "ths_rank": _to_int(row.get("order")),
                "popularity": popularity,
                "boards": boards,
            }
        return out

    async def _em_hot(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        """东方财富人气榜 → {code: {em_rank}} (App API, not the blocked push2 host)."""
        try:
            resp = await client.post(
                _EM_RANK_URL,
                json={
                    "appId": "appId01",
                    "globalId": "786e4c21-70dc-435a-93bb-38",
                    "marketType": "",
                    "pageNo": 1,
                    "pageSize": 100,
                },
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
        except Exception as exc:
            logger.warning("market: 东方财富 hot rank failed: {}", exc)
            return {}
        out: dict[str, dict[str, Any]] = {}
        for i, entry in enumerate(data):
            sc = str(entry.get("sc", "")).strip()  # e.g. SZ301308 / SH600580
            if len(sc) < 3:
                continue
            out[sc[2:]] = {"em_rank": _to_int(entry.get("rk"), default=i + 1)}
        return out

    async def _tencent_quotes(self, client: httpx.AsyncClient, codes: list[str]) -> dict[str, dict[str, Any]]:
        """腾讯行情 → {code: {name, change_pct, price}} for authoritative names."""
        out: dict[str, dict[str, Any]] = {}
        for chunk in _chunks(codes, _TX_CHUNK):
            symbols = ",".join(_tx_symbol(c) for c in chunk)
            try:
                resp = await client.get(_TX_QUOTE_URL + symbols)
                resp.encoding = "gbk"
                text = resp.text
            except Exception as exc:
                logger.warning("market: 腾讯 quote chunk failed: {}", exc)
                continue
            for line in text.strip().splitlines():
                parts = line.split("~")
                if len(parts) < 33 or not parts[2]:
                    continue
                out[parts[2]] = {
                    "name": parts[1],
                    "price": _to_optional_float(parts[3]),
                    "change_pct": _to_float(parts[32]),
                }
        return out

    # ---- merge -------------------------------------------------------------

    def _merge(
        self,
        ths: dict[str, dict[str, Any]],
        em: dict[str, dict[str, Any]],
        quotes: dict[str, dict[str, Any]],
    ) -> list[HotItem]:
        now = datetime.now(UTC)
        items: list[HotItem] = []
        for code in set(ths) | set(em):
            t = ths.get(code) or {}
            e = em.get(code) or {}
            q = quotes.get(code) or {}
            ths_rank = t.get("ths_rank") or None
            em_rank = e.get("em_rank") or None
            # Popularity score: nearer the top of either board scores higher.
            score = 0.0
            if em_rank:
                score += max(0.0, 200.0 - em_rank)
            if ths_rank:
                score += max(0.0, 200.0 - ths_rank)
            sources = []
            if em_rank:
                sources.append("东方财富")
            if ths_rank:
                sources.append("同花顺")
            change = q.get("change_pct")
            if change is None:
                change = t.get("change_pct", 0.0)
            items.append(
                HotItem(
                    rank=0,
                    symbol=code,
                    name=q.get("name") or t.get("name") or code,
                    boards=_to_int(t.get("boards")),
                    change_pct=float(change),
                    reason=t.get("popularity", "") or t.get("concept", ""),
                    concept=t.get("concept", ""),
                    hot_score=score,
                    latest_price=q.get("price"),
                    eastmoney_rank=em_rank,
                    tonghuashun_rank=ths_rank,
                    sources=sources or ["热榜"],
                    updated_at=now,
                )
            )
        items.sort(key=lambda it: (-it.hot_score, it.eastmoney_rank or 9999, it.tonghuashun_rank or 9999))
        for index, item in enumerate(items, start=1):
            item.rank = index
        return items[:_TOP_N]


_BOARD_RE = re.compile(r"(\d+)连板|\d+天(\d+)板")


def _parse_boards(tag: str) -> int:
    """连板 tag → board count. '4天3板'→3, '2连板'→2, '首板'→1."""
    if "首板" in tag:
        return 1
    match = _BOARD_RE.search(tag)
    if match:
        return _to_int(match.group(1) or match.group(2))
    return 0


def _chunks(seq: list[str], size: int) -> list[list[str]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def _tx_symbol(code: str) -> str:
    if code.startswith("6"):
        return "sh" + code
    if code[:1] in ("4", "8") or code.startswith("92"):
        return "bj" + code
    return "sz" + code


def _to_float(value: Any) -> float:
    try:
        return float(str(value).replace("%", "").strip() or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _to_optional_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(float(str(value).strip() or default))
    except (TypeError, ValueError):
        return default
