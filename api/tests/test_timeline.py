from datetime import date, datetime, time

from app.config import UTC
from app.timeline import cutoff_utc, delivery_slots, delivery_window


def test_cutoff_in_january_is_same_as_utc():
    assert cutoff_utc(date(2026, 1, 1), time(9, 20)) == datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


def test_cutoff_in_summer_is_one_hour_earlier_in_utc():
    assert cutoff_utc(date(2026, 7, 1), time(9, 20)) == datetime(2026, 7, 1, 8, 20, tzinfo=UTC)


def test_buy_jan_1_delivers_jan_2_in_48_slots():
    slots = delivery_slots(date(2026, 1, 1))
    assert len(slots) == 48
    assert slots[0] == datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
    assert slots[24] == datetime(2026, 1, 2, 12, 0, tzinfo=UTC)  # settlement period 25
    assert slots[-1] == datetime(2026, 1, 2, 23, 30, tzinfo=UTC)


def test_clock_change_days_have_46_and_50_slots():
    assert len(delivery_slots(date(2026, 3, 28))) == 46  # delivery 29 Mar, clocks go forward
    assert len(delivery_slots(date(2026, 10, 24))) == 50  # delivery 25 Oct, clocks go back


def test_delivery_window_for_january_buys():
    start, end = delivery_window(date(2026, 1, 1), date(2026, 1, 31))
    assert start == datetime(2026, 1, 2, tzinfo=UTC)
    assert end == datetime(2026, 2, 2, tzinfo=UTC)  # exclusive: all of Feb 1 is included
