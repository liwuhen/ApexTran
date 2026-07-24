"""Normalized market domain models.

These are the wire shapes the frontend consumes. Every source adapter maps its
upstream payload onto these, so swapping sources never touches the API or UI.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class FlashLevel(StrEnum):
    normal = "normal"
    important = "important"


class HotItem(BaseModel):
    """A row on the hotlist / 连板天梯."""

    rank: int
    symbol: str
    name: str
    boards: int = Field(0, description="连板数")
    change_pct: float = 0.0
    reason: str = ""
    concept: str = Field(default="", description="所属板块 / 行业,如 半导体、白酒")
    hot_score: float = 0.0
    latest_price: float | None = None
    eastmoney_rank: int | None = None
    tonghuashun_rank: int | None = None
    kai_pan_la_rank: int | None = None
    tao_gu_ba_rank: int | None = None
    sources: list[str] = Field(default_factory=list)
    updated_at: datetime


class StockSearchItem(BaseModel):
    """A searchable stock row for custom watchlists."""

    symbol: str
    name: str
    market: str = ""
    latest_price: float | None = None
    change_pct: float | None = None
    turnover_rate: float | None = Field(default=None, description="换手率，单位：百分点")
    amount: float | None = Field(default=None, description="成交额，单位：人民币元")
    float_market_cap: float | None = Field(default=None, description="流通市值，单位：人民币元")
    total_market_cap: float | None = Field(default=None, description="总市值，单位：人民币元")
    concept: str = ""
    source: str = ""
    updated_at: datetime


class StockQuoteItem(BaseModel):
    """A short-lived quote snapshot for a public instrument."""

    symbol: str
    market: str = ""
    latest_price: float | None = None
    change_pct: float | None = None
    turnover_rate: float | None = Field(default=None, description="换手率，单位：百分点")
    amount: float | None = Field(default=None, description="成交额，单位：人民币元")
    float_market_cap: float | None = Field(default=None, description="流通市值，单位：人民币元")
    total_market_cap: float | None = Field(default=None, description="总市值，单位：人民币元")
    source: str = ""
    updated_at: datetime


class KlineBar(BaseModel):
    """One 前复权 daily candle. ``volume`` is in 手 (100 shares), as A-share sources quote it."""

    date: str = Field(description="交易日, YYYY-MM-DD")
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class IntradayPoint(BaseModel):
    """One minute of the 分时图. ``avg_price`` is the session VWAP up to this minute."""

    time: str = Field(description="HH:MM, 交易所本地时间")
    price: float
    avg_price: float | None = None


class IntradaySeries(BaseModel):
    """A single trading day's 分时 curve, with the 昨收 baseline the chart draws against."""

    symbol: str
    date: str = Field(default="", description="交易日, YYYY-MM-DD")
    prev_close: float | None = None
    points: list[IntradayPoint] = Field(default_factory=list)
    updated_at: datetime


class Watchlist(BaseModel):
    """A user-owned watchlist group."""

    id: UUID
    name: str
    is_default: bool = False
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime


class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    sort_order: int = 0


class WatchlistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    sort_order: int | None = None


class WatchlistItemCreate(BaseModel):
    """Temporary create payload until stock_instruments supplies stable IDs."""

    symbol: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    market: str = ""
    concept: str = ""
    source: str = ""
    updated_at: datetime
    sort_order: int = 0
    note: str = ""


class WatchlistItem(BaseModel):
    """A user-owned watchlist entry with current public stock metadata."""

    id: UUID
    instrument: StockSearchItem
    sort_order: int = 0
    note: str = ""
    created_at: datetime
    updated_at: datetime


class WatchlistItemWithQuote(WatchlistItem):
    """A watchlist entry optionally enriched with the latest quote snapshot."""

    quote: StockQuoteItem | None = None


class WatchlistItemOrder(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    market: str = ""
    sort_order: int


class WatchlistItemOrderUpdate(BaseModel):
    items: list[WatchlistItemOrder] = Field(default_factory=list, max_length=500)


class NewsItem(BaseModel):
    """A headline or curated news item."""

    id: str
    title: str
    summary: str = ""
    source: str = ""
    url: str = ""
    tags: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    sentiment: float | None = None
    heat: int | None = None
    views: int | None = None
    # Optional: heat-ranked feeds (e.g. 雪球 hot topics) carry no publish time.
    published_at: datetime | None = None


class FlashItem(BaseModel):
    """A 7x24 快讯 entry."""

    id: str
    content: str
    title: str = ""
    # Publisher, e.g. 财联社 / 华尔街见闻 — used to group the 7x24 flash tabs.
    source: str = ""
    url: str = ""
    level: FlashLevel = FlashLevel.normal
    symbols: list[str] = Field(default_factory=list)
    published_at: datetime
