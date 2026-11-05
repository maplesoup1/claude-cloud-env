"""Trading-session calendar (regular hours per date, including half days).

Without a calendar every weekday is assumed to be 9:30-16:00. Backtests on
Alpaca data load the real calendar, so on half days (13:00 close) bars after
the close are ignored and the flatten time moves earlier, exactly as in live.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .models import MARKET_CLOSE, MARKET_OPEN, NY


@dataclass
class SessionCalendar:
    sessions: dict[date, tuple[time, time]] = field(default_factory=dict)  # date -> (open, close)
    strict: bool = False  # True: dates missing from `sessions` are holidays

    def hours(self, d: date) -> tuple[time, time] | None:
        if d in self.sessions:
            return self.sessions[d]
        return None if self.strict else (MARKET_OPEN, MARKET_CLOSE)

    def in_session(self, ts: datetime) -> bool:
        ts = ts.astimezone(NY)
        h = self.hours(ts.date())
        return h is not None and h[0] <= ts.time() < h[1]

    def close(self, d: date) -> time | None:
        h = self.hours(d)
        return h[1] if h else None

    def flatten_time(self, d: date, configured: time, minutes_before_close: int = 15) -> time:
        """The configured flatten time, pulled in on early-close days."""
        c = self.close(d)
        if c is None or c >= MARKET_CLOSE:
            return configured
        early = (datetime.combine(d, c) - timedelta(minutes=minutes_before_close)).time()
        return min(configured, early)

    @classmethod
    def from_alpaca(cls, trading_client, start: date, end: date) -> "SessionCalendar":
        from alpaca.trading.requests import GetCalendarRequest

        days = trading_client.get_calendar(GetCalendarRequest(start=start, end=end))
        return cls({c.date: (c.open.time(), c.close.time()) for c in days}, strict=True)


DEFAULT_CALENDAR = SessionCalendar()
