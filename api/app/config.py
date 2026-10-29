"""Central configuration.

Everything the decision window depends on lives here, so changing the
assumptions (for example the cutoff time) is a one-line edit or an env var.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, time, timedelta, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
UTC = timezone.utc


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./local.db"
    bmrs_base_url: str = "https://data.elexon.co.uk/bmrs/api/v1"
    # Buy dates are the days on which the purchase decision is made.
    first_buy_date: date = date(2026, 1, 1)
    last_buy_date: date = date(2026, 1, 31)
    # Day-ahead decision cutoff, UK local time on the buy date.
    cutoff_local: time = time(9, 20)
    # Forecasts are pulled from this publish date, a bit before the first buy date.
    forecast_publish_from: date = date(2025, 12, 29)

    @property
    def first_delivery_date(self) -> date:
        return self.first_buy_date + timedelta(days=1)

    @property
    def last_delivery_date(self) -> date:
        return self.last_buy_date + timedelta(days=1)


def load_settings() -> Settings:
    d = Settings()
    return Settings(
        database_url=os.getenv("DATABASE_URL", d.database_url),
        bmrs_base_url=os.getenv("BMRS_BASE_URL", d.bmrs_base_url),
        first_buy_date=date.fromisoformat(os.getenv("FIRST_BUY_DATE", d.first_buy_date.isoformat())),
        last_buy_date=date.fromisoformat(os.getenv("LAST_BUY_DATE", d.last_buy_date.isoformat())),
        cutoff_local=time.fromisoformat(os.getenv("CUTOFF_LOCAL", "09:20")),
        forecast_publish_from=date.fromisoformat(
            os.getenv("FORECAST_PUBLISH_FROM", d.forecast_publish_from.isoformat())
        ),
    )
