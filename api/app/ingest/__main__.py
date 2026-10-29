"""Usage:
    python -m app.ingest run      # pull from BMRS and load the database
    python -m app.ingest report   # check what is loaded
"""
from __future__ import annotations

import argparse
import logging

from ..config import load_settings
from ..db import init_db, make_engine
from .bmrs import BmrsClient
from .report import build_report, format_report
from .runner import run_ingest


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--skip-actuals", action="store_true")
    run.add_argument("--skip-forecasts", action="store_true")
    sub.add_parser("report")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    engine = make_engine(settings.database_url)

    if args.cmd == "run":
        client = BmrsClient(settings.bmrs_base_url)
        counts = run_ingest(
            settings,
            client,
            engine,
            do_actuals=not args.skip_actuals,
            do_forecasts=not args.skip_forecasts,
        )
        print("rows before:", counts["before"], "after:", counts["after"])
    init_db(engine)
    print(format_report(build_report(engine, settings)))


if __name__ == "__main__":
    main()
