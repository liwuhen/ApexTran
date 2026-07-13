"""HTTP surface for the market module — public, cacheable, versioned.

Public endpoints set ``Cache-Control`` so a CDN collapses the fan-out (the whole
point at high concurrency): one origin fetch serves N users. See §6/§8.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from ...shared.security import CurrentUser, require_scope
from .domain.models import (
    FlashItem,
    HotItem,
    IntradaySeries,
    KlineBar,
    NewsItem,
    StockQuoteItem,
    StockSearchItem,
    Watchlist,
    WatchlistCreate,
    WatchlistItem,
    WatchlistItemCreate,
    WatchlistItemOrderUpdate,
    WatchlistItemWithQuote,
    WatchlistUpdate,
)
from .provider import get_service
from .service import MarketService

router = APIRouter(prefix="/api/v1/market", tags=["market"])

# FastAPI-idiomatic DI: the service singleton, injected per request.
ServiceDep = Annotated[MarketService, Depends(get_service)]
WatchlistReadUserDep = Annotated[CurrentUser, Depends(require_scope("market:watchlists:read"))]
WatchlistWriteUserDep = Annotated[CurrentUser, Depends(require_scope("market:watchlists:write"))]

# Public data is identical for everyone → let the CDN cache it briefly.
_PUBLIC_CACHE = "public, s-maxage=2, stale-while-revalidate=10"
_PRIVATE_CACHE = "no-store"

# A-share codes are always six digits — pin the path param so a symbol can never
# reach an upstream URL as anything else.
SymbolDep = Annotated[str, Path(pattern=r"^\d{6}$")]


@router.get("/hotlist", response_model=list[HotItem])
async def hotlist(response: Response, service: ServiceDep) -> list[HotItem]:
    response.headers["Cache-Control"] = _PUBLIC_CACHE
    return await service.get_hotlist()


@router.get("/stocks/search", response_model=list[StockSearchItem])
async def stock_search(
    response: Response,
    service: ServiceDep,
    q: Annotated[str, Query(min_length=1, max_length=32)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[StockSearchItem]:
    response.headers["Cache-Control"] = _PUBLIC_CACHE
    return await service.search_stocks(q, limit)


@router.get("/quotes", response_model=list[StockQuoteItem])
async def quotes(
    response: Response,
    service: ServiceDep,
    symbols: Annotated[str, Query(min_length=1, max_length=4096)],
) -> list[StockQuoteItem]:
    response.headers["Cache-Control"] = _PUBLIC_CACHE
    return await service.get_quotes(symbols.split(","))


@router.get("/klines/{symbol}", response_model=list[KlineBar])
async def daily_klines(
    symbol: SymbolDep,
    response: Response,
    service: ServiceDep,
    limit: Annotated[int, Query(ge=20, le=500)] = 180,
    market: Annotated[str, Query(max_length=32)] = "",
) -> list[KlineBar]:
    response.headers["Cache-Control"] = _PUBLIC_CACHE
    return await service.get_daily_kline(symbol, limit, market)


@router.get("/intraday/{symbol}", response_model=IntradaySeries)
async def intraday(
    symbol: SymbolDep,
    response: Response,
    service: ServiceDep,
    market: Annotated[str, Query(max_length=32)] = "",
) -> IntradaySeries:
    response.headers["Cache-Control"] = _PUBLIC_CACHE
    return await service.get_intraday(symbol, market)


@router.get("/headlines", response_model=list[NewsItem])
async def headlines(response: Response, service: ServiceDep, symbol: str | None = None) -> list[NewsItem]:
    response.headers["Cache-Control"] = _PUBLIC_CACHE
    return await service.get_headlines(symbol)


@router.get("/news", response_model=list[NewsItem])
async def news(response: Response, service: ServiceDep, category: str | None = None) -> list[NewsItem]:
    response.headers["Cache-Control"] = _PUBLIC_CACHE
    return await service.get_news(category)


@router.get("/ai-hotspots", response_model=list[NewsItem])
async def ai_hotspots(response: Response, service: ServiceDep) -> list[NewsItem]:
    response.headers["Cache-Control"] = _PUBLIC_CACHE
    return await service.get_ai_hotspots()


@router.get("/flash", response_model=list[FlashItem])
async def flash(response: Response, service: ServiceDep) -> list[FlashItem]:
    response.headers["Cache-Control"] = _PUBLIC_CACHE
    return await service.get_flash()


@router.get("/watchlists", response_model=list[Watchlist])
async def watchlists(response: Response, service: ServiceDep, user: WatchlistReadUserDep) -> list[Watchlist]:
    response.headers["Cache-Control"] = _PRIVATE_CACHE
    return await service.list_watchlists(user.user_id)


@router.post("/watchlists", response_model=Watchlist, status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    watchlist: WatchlistCreate,
    response: Response,
    service: ServiceDep,
    user: WatchlistWriteUserDep,
) -> Watchlist:
    response.headers["Cache-Control"] = _PRIVATE_CACHE
    return await service.create_watchlist(user.user_id, watchlist)


@router.patch("/watchlists/{watchlist_id}", response_model=Watchlist)
async def update_watchlist(
    watchlist_id: UUID,
    patch: WatchlistUpdate,
    response: Response,
    service: ServiceDep,
    user: WatchlistWriteUserDep,
) -> Watchlist:
    response.headers["Cache-Control"] = _PRIVATE_CACHE
    watchlist = await service.update_watchlist(user.user_id, watchlist_id, patch)
    if watchlist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="watchlist not found")
    return watchlist


@router.delete("/watchlists/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(
    watchlist_id: UUID,
    response: Response,
    service: ServiceDep,
    user: WatchlistWriteUserDep,
) -> None:
    response.headers["Cache-Control"] = _PRIVATE_CACHE
    deleted = await service.delete_watchlist(user.user_id, watchlist_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="watchlist not found")


@router.get(
    "/watchlists/default/items",
    response_model=list[WatchlistItemWithQuote],
    response_model_exclude_unset=True,
)
async def default_watchlist_items(
    response: Response,
    service: ServiceDep,
    user: WatchlistReadUserDep,
    include_quotes: bool = False,
) -> list[WatchlistItemWithQuote]:
    response.headers["Cache-Control"] = _PRIVATE_CACHE
    return await service.list_default_watchlist_items(user.user_id, include_quotes=include_quotes)


@router.get(
    "/watchlists/{watchlist_id}/items",
    response_model=list[WatchlistItemWithQuote],
    response_model_exclude_unset=True,
)
async def watchlist_items(
    watchlist_id: UUID,
    response: Response,
    service: ServiceDep,
    user: WatchlistReadUserDep,
    include_quotes: bool = False,
) -> list[WatchlistItemWithQuote]:
    response.headers["Cache-Control"] = _PRIVATE_CACHE
    return await service.list_watchlist_items(user.user_id, watchlist_id, include_quotes=include_quotes)


@router.post("/watchlists/default/items", response_model=WatchlistItem, status_code=status.HTTP_201_CREATED)
async def add_default_watchlist_item(
    item: WatchlistItemCreate,
    response: Response,
    service: ServiceDep,
    user: WatchlistWriteUserDep,
) -> WatchlistItem:
    response.headers["Cache-Control"] = _PRIVATE_CACHE
    return await service.add_default_watchlist_item(user.user_id, item)


@router.post("/watchlists/{watchlist_id}/items", response_model=WatchlistItem, status_code=status.HTTP_201_CREATED)
async def add_watchlist_item(
    watchlist_id: UUID,
    item: WatchlistItemCreate,
    response: Response,
    service: ServiceDep,
    user: WatchlistWriteUserDep,
) -> WatchlistItem:
    response.headers["Cache-Control"] = _PRIVATE_CACHE
    try:
        return await service.add_watchlist_item(user.user_id, watchlist_id, item)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="watchlist not found") from exc


@router.delete("/watchlists/default/items/{symbol}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_default_watchlist_item(
    symbol: str,
    market: Annotated[str, Query(min_length=1)],
    response: Response,
    service: ServiceDep,
    user: WatchlistWriteUserDep,
) -> None:
    response.headers["Cache-Control"] = _PRIVATE_CACHE
    await service.remove_default_watchlist_item(user.user_id, market, symbol)


@router.delete("/watchlists/{watchlist_id}/items/{symbol}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_watchlist_item(
    watchlist_id: UUID,
    symbol: str,
    market: Annotated[str, Query(min_length=1)],
    response: Response,
    service: ServiceDep,
    user: WatchlistWriteUserDep,
) -> None:
    response.headers["Cache-Control"] = _PRIVATE_CACHE
    removed = await service.remove_watchlist_item(user.user_id, watchlist_id, market, symbol)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="watchlist item not found")


@router.patch("/watchlists/{watchlist_id}/items/order", response_model=list[WatchlistItem])
async def reorder_watchlist_items(
    watchlist_id: UUID,
    patch: WatchlistItemOrderUpdate,
    response: Response,
    service: ServiceDep,
    user: WatchlistWriteUserDep,
) -> list[WatchlistItem]:
    response.headers["Cache-Control"] = _PRIVATE_CACHE
    items = await service.reorder_watchlist_items(user.user_id, watchlist_id, patch.items)
    if not items and patch.items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="watchlist not found")
    return items
