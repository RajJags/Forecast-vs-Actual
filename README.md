# Wind forecast accuracy for day-ahead buying (work in progress)

## Assumptions
- Buy dates are Jan 1 to Jan 31 2026, so delivery days are Jan 2 to Feb 1 2026.
- For each delivery half-hour the buyer sees the latest forecast published before
  the cutoff (09:20 UK time) on the buy date. The cutoff is configurable.
- Wind only, national level, Elexon data only (FUELHH actuals, WINDFOR forecasts).
- Only forecasts for target times inside the delivery window are stored.

## Run it
    cp .env.example .env
    docker compose up -d db
    docker compose run --rm api python -m app.ingest run     # pull from BMRS (needs internet)
    docker compose run --rm api python -m app.ingest report  # check the loaded data
    docker compose run --rm api pytest                       # tests

## Layout
- `api/app/config.py`: window and cutoff settings
- `api/app/timeline.py`: buy dates, cutoffs, delivery slots (pure functions)
- `api/app/db.py`: tables and idempotent writes
- `api/app/ingest/`: BMRS client, loader, data check report
- `api/tests/`: unit tests

## AI tools
Built with assistance from Claude (Anthropic). To be expanded before submission.
