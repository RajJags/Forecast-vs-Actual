"""Pulls data from BMRS in chunks and loads it into the database.

Safe to run repeatedly: forecasts are insert-if-missing, actuals are refreshed.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Iterator

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from ..config import UTC, Settings
from ..db import actuals, forecasts, init_db, write_rows
from ..timeline import delivery_window
from .bmrs import BmrsClient

log = logging.getLogger(__name__)


def date_windows(first: date, last: date, days: int) -> Iterator[tuple[date, date]]:
    """Inclusive date ranges of at most `days` days that tile [first, last]."""
    start = first
    while start <= last:
        end = min(start + timedelta(days=days - 1), last)
        yield start, end
        start = end + timedelta(days=1)


def time_windows(start: datetime, end: datetime, step: timedelta) -> Iterator[tuple[datetime, datetime]]:
    """Back-to-back windows that tile [start, end)."""
    cur = start
    while cur < end:
        nxt = min(cur + step, end)
        yield cur, nxt
        cur = nxt


def ingest_actuals(client: BmrsClient, engine: Engine, first_day: date, last_day: date, chunk_days: int = 7) -> None:
    for a, b in date_windows(first_day, last_day, chunk_days):
        # The docs do not say whether settlementDateTo is inclusive, so ask for one
        # day extra and keep only rows inside [a, b]. Duplicates are harmless.
        fetched = client.fetch_wind_actuals(a, b + timedelta(days=1))
        rows = [r for r in fetched if a <= r["settlement_date"] <= b]
        with engine.begin() as conn:
            write_rows(conn, actuals, rows, update_existing=True)
        log.info("actuals %s..%s: fetched %d, kept %d", a, b, len(fetched), len(rows))


def ingest_forecasts(
    client: BmrsClient,
    engine: Engine,
    publish_from: datetime,
    publish_to: datetime,
    target_from: datetime,
    target_to: datetime,
    step: timedelta = timedelta(hours=24),
) -> None:
    for a, b in time_windows(publish_from, publish_to, step):
        fetched = client.fetch_wind_forecasts(a, b)
        # Keep only forecasts for target times inside the delivery window.
        rows = [
            r
            for r in fetched
            if a <= r["publish_time"] <= b and target_from <= r["start_time"] < target_to
        ]
        with engine.begin() as conn:
            write_rows(conn, forecasts, rows)
        log.info("forecasts published %s..%s: fetched %d, kept %d", a, b, len(fetched), len(rows))


def table_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            "actuals": conn.scalar(select(func.count()).select_from(actuals)) or 0,
            "forecasts": conn.scalar(select(func.count()).select_from(forecasts)) or 0,
        }


def run_ingest(
    settings: Settings,
    client: BmrsClient,
    engine: Engine,
    *,
    do_actuals: bool = True,
    do_forecasts: bool = True,
) -> dict[str, dict[str, int]]:
    init_db(engine)
    before = table_counts(engine)
    target_from, target_to = delivery_window(settings.first_buy_date, settings.last_buy_date)

    if do_actuals:
        ingest_actuals(client, engine, settings.first_delivery_date, settings.last_delivery_date)
    if do_forecasts:
        publish_from = datetime.combine(settings.forecast_publish_from, time(0), tzinfo=UTC)
        publish_to = datetime.combine(settings.last_buy_date + timedelta(days=1), time(0), tzinfo=UTC)
        ingest_forecasts(client, engine, publish_from, publish_to, target_from, target_to)

    return {"before": before, "after": table_counts(engine)}
