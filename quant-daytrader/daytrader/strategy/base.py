from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from ..models import Bar, Signal


class Strategy(ABC):
    """A strategy sees completed N-minute bars and may emit entry signals.

    Exits are handled by bracket orders (stop + target) and by the engine's
    end-of-day flatten, so strategies only decide entries.
    """

    @abstractmethod
    def on_bar(self, bar: Bar) -> Signal | None: ...

    def mark_traded(self, symbol: str, day: date) -> None:
        """Called on live start-up for symbols already traded today (restart safety)."""
