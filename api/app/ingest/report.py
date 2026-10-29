"""Data check: is what we loaded complete and shaped the way the app assumes?"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from ..config import Settings
from ..db import actuals, forecasts
from ..timeline import as_utc, buy_dates, cutoff_utc, delivery_date, delivery_slots


def build_report(engine: Engine, settings: Settings) -> dict:
    report: dict = {}

    with engine.connect() as conn:
        # Actuals: every delivery day should have a full set of slots.
        actual_slots = {as_utc(s) for (s,) in conn.execute(select(actuals.c.start_time))}
        slot_starts = sorted(actual_slots)

        missing_actual_days: list[tuple[date, int, int]] = []
        for bd in buy_dates(settings.first_buy_date, settings.last_buy_date):
            expected = delivery_slots(bd)
            have = sum(1 for s in expected if s in actual_slots)
            if have != len(expected):
                missing_actual_days.append((delivery_date(bd), have, len(expected)))

        report["actuals"] = {
            "rows": len(actual_slots),
            "first": slot_starts[0] if slot_starts else None,
            "last": slot_starts[-1] if slot_starts else None,
            "days_incomplete": missing_actual_days,
        }

        # Forecasts: resolution, publish cadence, horizon range.
        rows = conn.execute(select(forecasts.c.start_time, forecasts.c.publish_time)).all()
        minutes = Counter()
        publish_times: set[datetime] = set()
        horizons: list[float] = []
        for start, pub in rows:
            s, p = as_utc(start), as_utc(pub)
            minutes[s.minute] += 1
            publish_times.add(p)
            horizons.append((s - p).total_seconds() / 3600)
        report["forecasts"] = {
            "rows": len(rows),
            "distinct_publish_times": len(publish_times),
            "first_publish": min(publish_times) if publish_times else None,
            "last_publish": max(publish_times) if publish_times else None,
            "start_minute_values": dict(sorted(minutes.items())),
            "horizon_hours_min": round(min(horizons), 2) if horizons else None,
            "horizon_hours_max": round(max(horizons), 2) if horizons else None,
        }

        # Coverage: for each buy date, which delivery slots have NO forecast
        # published before the cutoff? Those slots could not be shown to a buyer.
        uncovered: list[tuple[date, int, int]] = []
        for bd in buy_dates(settings.first_buy_date, settings.last_buy_date):
            slots = delivery_slots(bd)
            cutoff = cutoff_utc(bd, settings.cutoff_local)
            covered = conn.scalar(
                select(func.count(func.distinct(forecasts.c.start_time))).where(
                    forecasts.c.start_time >= slots[0],
                    forecasts.c.start_time <= slots[-1],
                    forecasts.c.publish_time <= cutoff,
                )
            ) or 0
            if covered != len(slots):
                uncovered.append((bd, covered, len(slots)))
        report["decision_coverage_gaps"] = uncovered

    return report


def _brief(items: list, show: int = 3) -> str:
    if not items:
        return "none"
    shown = ", ".join(str(i) for i in items[:show])
    return f"{len(items)} found, first {min(show, len(items))}: {shown}"


def format_report(r: dict) -> str:
    a, f = r["actuals"], r["forecasts"]
    lines = [
        "ACTUALS (FUELHH, WIND)",
        f"  rows: {a['rows']}   first: {a['first']}   last: {a['last']}",
        f"  delivery days with missing slots: {_brief(a['days_incomplete'])}",
        "FORECASTS (WINDFOR)",
        f"  rows: {f['rows']}   distinct publish times: {f['distinct_publish_times']}",
        f"  first publish: {f['first_publish']}   last publish: {f['last_publish']}",
        f"  start-time minute values (0/30 = half-hourly, 0 only = hourly): {f['start_minute_values']}",
        f"  forecast horizon (hours ahead): {f['horizon_hours_min']} to {f['horizon_hours_max']}",
        "DECISION COVERAGE",
        f"  buy dates where some delivery slot has no forecast before the cutoff: "
        f"{_brief(r['decision_coverage_gaps'])}",
    ]
    return "\n".join(lines)
