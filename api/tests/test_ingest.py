from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.config import UTC, Settings
from app.db import actuals, forecasts, init_db, make_engine
from app.ingest.bmrs import BmrsClient, BmrsError
from app.ingest.report import build_report
from app.ingest.runner import date_windows, run_ingest, time_windows
from app.timeline import as_utc

# Small window: buy Jan 1 and Jan 2, so delivery Jan 2 and Jan 3.
SETTINGS = Settings(
    database_url="sqlite://",
    first_buy_date=date(2026, 1, 1),
    last_buy_date=date(2026, 1, 2),
    forecast_publish_from=date(2025, 12, 31),
)


def z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fake_actuals(first_day: date, days: int):
    rows = []
    for d in range(days):
        day = first_day + timedelta(days=d)
        for n in range(48):
            start = datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(minutes=30 * n)
            rows.append({
                "dataset": "FUELHH", "publishTime": z(start), "startTime": z(start),
                "settlementDate": day.isoformat(), "settlementPeriod": n + 1,
                "fuelType": "WIND", "generation": 4000 + n,
            })
    return rows


def make_client(handler, **kw):
    return BmrsClient(
        "https://example.test/api",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda s: None,
        **kw,
    )


@pytest.fixture
def engine():
    e = make_engine("sqlite://")
    init_db(e)
    return e


def test_windows_tile_without_gaps():
    assert list(date_windows(date(2026, 1, 2), date(2026, 2, 1), 7))[-1] == (date(2026, 1, 30), date(2026, 2, 1))
    assert len(list(date_windows(date(2026, 1, 2), date(2026, 2, 1), 7))) == 5
    wins = list(time_windows(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 3, 12, tzinfo=UTC), timedelta(days=1)))
    assert wins[0][1] == wins[1][0] and wins[-1][1] == datetime(2026, 1, 3, 12, tzinfo=UTC)


def test_full_run_is_idempotent_and_filters(engine):
    all_actuals = fake_actuals(date(2026, 1, 2), 3)  # Jan 2, 3, 4: Jan 4 is outside the window

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/FUELHH/stream"):
            assert req.url.params.get_list("fuelType") == ["WIND"]
            lo = date.fromisoformat(req.url.params["settlementDateFrom"])
            hi = date.fromisoformat(req.url.params["settlementDateTo"])  # treat as inclusive
            rows = [r for r in all_actuals if lo <= date.fromisoformat(r["settlementDate"]) <= hi]
            # a non-wind row and a null row must be ignored
            rows += [{**rows[0], "fuelType": "SOLAR"}, {**rows[1], "generation": None}] if rows else []
            return httpx.Response(200, json=rows)
        if req.url.path.endswith("/WINDFOR/stream"):
            lo = datetime.fromisoformat(req.url.params["publishDateTimeFrom"].replace("Z", "+00:00"))
            hi = datetime.fromisoformat(req.url.params["publishDateTimeTo"].replace("Z", "+00:00"))
            out = []
            pub = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
            if lo <= pub <= hi:
                out.append({"dataset": "WINDFOR", "publishTime": z(pub), "startTime": "2026-01-02T12:00:00Z", "generation": 4500})
                # target time outside the delivery window: must be dropped
                out.append({"dataset": "WINDFOR", "publishTime": z(pub), "startTime": "2026-02-10T12:00:00Z", "generation": 1})
            return httpx.Response(200, json=out)
        return httpx.Response(404)

    client = make_client(handler)
    first = run_ingest(SETTINGS, client, engine)
    assert first["after"] == {"actuals": 96, "forecasts": 1}  # Jan 2 and Jan 3 only

    second = run_ingest(SETTINGS, client, engine)  # run again: nothing doubles
    assert second["after"] == first["after"]

    with engine.connect() as conn:
        row = conn.execute(select(actuals).where(actuals.c.settlement_period == 25, actuals.c.settlement_date == date(2026, 1, 2))).one()
        assert as_utc(row.start_time) == datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
        assert row.generation_mw == 4024


def test_retries_429_then_succeeds():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json=[])

    assert make_client(handler).fetch_wind_actuals(date(2026, 1, 2), date(2026, 1, 3)) == []
    assert calls["n"] == 3


def test_400_fails_immediately():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(400, text="bad parameter")

    with pytest.raises(BmrsError):
        make_client(handler).fetch_wind_actuals(date(2026, 1, 2), date(2026, 1, 3))
    assert calls["n"] == 1


def test_report_flags_missing_slots_and_coverage_gaps(engine):
    # Only 47 of 48 actual slots for Jan 2, and a forecast published AFTER the cutoff.
    rows = fake_actuals(date(2026, 1, 2), 1)[:47]
    from app.db import write_rows
    with engine.begin() as conn:
        write_rows(conn, actuals, [
            {"start_time": datetime.fromisoformat(r["startTime"].replace("Z", "+00:00")),
             "settlement_date": date.fromisoformat(r["settlementDate"]),
             "settlement_period": r["settlementPeriod"], "generation_mw": r["generation"]} for r in rows])
        write_rows(conn, forecasts, [{
            "start_time": datetime(2026, 1, 2, 12, tzinfo=UTC),
            "publish_time": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),  # after the 09:20 cutoff
            "generation_mw": 4300}])

    rep = build_report(engine, SETTINGS)
    assert rep["actuals"]["days_incomplete"][0] == (date(2026, 1, 2), 47, 48)
    # the late forecast does not count: buy date Jan 1 has 0 of 48 covered
    assert rep["decision_coverage_gaps"][0] == (date(2026, 1, 1), 0, 48)
