"""Zero-dependency stub source so the module runs out of the box."""

from __future__ import annotations

from ..domain.models import Widget


class MockWidgetSource:
    async def fetch_widgets(self) -> list[Widget]:
        return [Widget(id="1", label="示例组件")]
