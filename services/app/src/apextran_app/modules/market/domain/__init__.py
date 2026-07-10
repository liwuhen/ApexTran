"""Pure domain models — no IO. Normalized shapes that hide upstream differences."""

from .models import FlashItem, HotItem, NewsItem

__all__ = ["FlashItem", "HotItem", "NewsItem"]
