"""Thin client for the BMRS (Elexon Insights) stream endpoints.

Only knows how to fetch and parse. Retries on 429 and 5xx with backoff.
A 400 is a bug in our query, so it fails loudly instead of retrying.
"""
from __future__ import annotations

import logging
import time as time_module
from datetime import date, datetime
from typing import Any, Callable

import httpx

from ..config import UTC

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class BmrsError(RuntimeError):
    pass


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:  # BMRS times are UTC; never let the system timezone leak in
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_actual(raw: dict[str, Any]) -> dict[str, Any] | None:
    if raw.get("fuelType") != "WIND" or raw.get("generation") is None:
        return None
    return {
        "start_time": parse_time(raw["startTime"]),
        "settlement_date": date.fromisoformat(raw["settlementDate"]),
        "settlement_period": int(raw["settlementPeriod"]),
        "generation_mw": float(raw["generation"]),
    }


def parse_forecast(raw: dict[str, Any]) -> dict[str, Any] | None:
    if raw.get("generation") is None:
        return None
    return {
        "start_time": parse_time(raw["startTime"]),
        "publish_time": parse_time(raw["publishTime"]),
        "generation_mw": float(raw["generation"]),
    }


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class BmrsClient:
    def __init__(
        self,
        base_url: str,
        http: httpx.Client | None = None,
        max_retries: int = 5,
        backoff_s: float = 1.0,
        sleep: Callable[[float], None] = time_module.sleep,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=60)
        self._max_retries = max_retries
        self._backoff = backoff_s
        self._sleep = sleep

    def _get_json(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        url = f"{self._base}{path}"
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._http.get(url, params=params)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise BmrsError(f"network error after retries: {exc}") from exc
                self._wait(attempt, None, f"network error {exc!r}")
                continue

            if resp.status_code in RETRY_STATUSES:
                if attempt == self._max_retries:
                    raise BmrsError(f"{resp.status_code} after {attempt + 1} attempts: {url}")
                self._wait(attempt, resp.headers.get("Retry-After"), f"HTTP {resp.status_code}")
                continue
            if resp.status_code >= 400:
                raise BmrsError(f"HTTP {resp.status_code} for {url} {params}: {resp.text[:300]}")

            data = resp.json()
            if isinstance(data, dict) and "data" in data:  # tolerate wrapped payloads
                data = data["data"]
            if not isinstance(data, list):
                raise BmrsError(f"unexpected payload shape from {url}: {type(data).__name__}")
            return data
        raise BmrsError("unreachable")

    def _wait(self, attempt: int, retry_after: str | None, why: str) -> None:
        delay = self._backoff * (2**attempt)
        if retry_after and retry_after.isdigit():
            delay = max(delay, float(retry_after))
        log.warning("%s, retrying in %.1fs (attempt %d)", why, delay, attempt + 1)
        self._sleep(delay)

    def fetch_wind_actuals(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        raw = self._get_json(
            "/datasets/FUELHH/stream",
            {
                "settlementDateFrom": date_from.isoformat(),
                "settlementDateTo": date_to.isoformat(),
                "fuelType": ["WIND"],
            },
        )
        return [r for r in map(parse_actual, raw) if r is not None]

    def fetch_wind_forecasts(self, publish_from: datetime, publish_to: datetime) -> list[dict[str, Any]]:
        raw = self._get_json(
            "/datasets/WINDFOR/stream",
            {"publishDateTimeFrom": _iso(publish_from), "publishDateTimeTo": _iso(publish_to)},
        )
        return [r for r in map(parse_forecast, raw) if r is not None]
