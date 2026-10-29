"""Tables and write helpers. Times are stored in UTC."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from sqlalchemy import Column, Date, DateTime, Float, Integer, MetaData, Table, create_engine
from sqlalchemy.engine import Connection, Engine

metadata = MetaData()

# Half-hourly wind outturn (FUELHH, fuelType WIND).
actuals = Table(
    "actuals",
    metadata,
    Column("start_time", DateTime(timezone=True), primary_key=True),
    Column("settlement_date", Date, nullable=False),
    Column("settlement_period", Integer, nullable=False),
    Column("generation_mw", Float, nullable=False),
)

# Every published wind forecast version (WINDFOR). The composite primary key
# also serves the "latest forecast before the cutoff" lookup.
forecasts = Table(
    "forecasts",
    metadata,
    Column("start_time", DateTime(timezone=True), primary_key=True),
    Column("publish_time", DateTime(timezone=True), primary_key=True),
    Column("generation_mw", Float, nullable=False),
)

BATCH = 5000


def make_engine(url: str) -> Engine:
    return create_engine(url, future=True)


def init_db(engine: Engine) -> None:
    metadata.create_all(engine)


def write_rows(
    conn: Connection,
    table: Table,
    rows: Sequence[Mapping[str, Any]],
    *,
    update_existing: bool = False,
) -> None:
    """Idempotent bulk write.

    update_existing=False: rows that already exist are left alone (forecasts never change).
    update_existing=True: rows that already exist are refreshed (actuals can be revised).
    """
    if not rows:
        return
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif conn.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise NotImplementedError(f"unsupported dialect {conn.dialect.name}")

    pk = [c.name for c in table.primary_key.columns]
    # Drop duplicate keys inside the payload; the last occurrence wins.
    unique = list({tuple(r[k] for k in pk): dict(r) for r in rows}.values())

    for i in range(0, len(unique), BATCH):
        stmt = insert(table)
        if update_existing:
            stmt = stmt.on_conflict_do_update(
                index_elements=pk,
                set_={c.name: stmt.excluded[c.name] for c in table.columns if c.name not in pk},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=pk)
        conn.execute(stmt, unique[i : i + BATCH])
