"""Pure date and time helpers: buy dates, cutoffs and delivery slots.

No database or web code here, so it is trivial to unit test.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterator

from .config import LONDON, UTC

SLOT = timedelta(minutes=30)


def as_utc(dt: datetime) -> datetime:
    """Treat naive datetimes (e.g. read back from SQLite) as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def buy_dates(first: date, last: date) -> Iterator[date]:
    d = first
    while d <= last:
        yield d
        d += timedelta(days=1)


def delivery_date(buy_date: date) -> date:
    return buy_date + timedelta(days=1)


def cutoff_utc(buy_date: date, cutoff_local: time) -> datetime:
    """The moment the buyer must decide, as a UTC instant."""
    return datetime.combine(buy_date, cutoff_local, tzinfo=LONDON).astimezone(UTC)


def _london_midnight_utc(d: date) -> datetime:
    return datetime.combine(d, time(0), tzinfo=LONDON).astimezone(UTC)


def delivery_slots(buy_date: date) -> list[datetime]:
    """UTC start times of every half-hour of the delivery day.

    48 slots normally, 46 or 50 on the days the clocks change.
    """
    day = delivery_date(buy_date)
    start = _london_midnight_utc(day)
    end = _london_midnight_utc(day + timedelta(days=1))
    slots, t = [], start
    while t < end:
        slots.append(t)
        t += SLOT
    return slots


def delivery_window(first_buy: date, last_buy: date) -> tuple[datetime, datetime]:
    """[start, end) in UTC covering every delivery day of the buy-date range."""
    return (
        _london_midnight_utc(delivery_date(first_buy)),
        _london_midnight_utc(delivery_date(last_buy) + timedelta(days=1)),
    )
