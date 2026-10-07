"""Load the demo Parquet dataset into ClickHouse (TZ scenario 1: connect ClickHouse, get a dashboard).

uv run python -m scripts.load_demo_clickhouse --url http://platform:platform@localhost:8123 --src ./demo-data
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

import clickhouse_connect
import pyarrow as pa
import pyarrow.parquet as pq

TYPES = {
    pa.string(): "String",
    pa.large_string(): "String",
    pa.int32(): "Int32",
    pa.int64(): "Int64",
    pa.float64(): "Float64",
    pa.float32(): "Float32",
    pa.bool_(): "Bool",
    pa.date32(): "Date",
}
ORDER_BY = {"events": "(app_id, event_date, event_name)", "mart_retention": "(app_id, install_date, day_n)"}


def ch_type(t: pa.DataType) -> str:
    if pa.types.is_timestamp(t):
        return "DateTime"
    if pa.types.is_decimal(t):
        return "Float64"
    return TYPES.get(t, "String")


def load(url: str, src: Path, database: str = "demo") -> dict[str, int]:
    u = urlparse(url)
    client = clickhouse_connect.get_client(
        host=u.hostname or "localhost", port=u.port or 8123, username=u.username or "default", password=u.password or ""
    )
    client.command(f"CREATE DATABASE IF NOT EXISTS {database}")
    counts = {}
    for path in sorted(src.glob("*.parquet")):
        table = pq.read_table(path)
        cols = ", ".join(f"`{f.name}` {ch_type(f.type)}" for f in table.schema)
        name = path.stem
        client.command(f"DROP TABLE IF EXISTS {database}.{name}")
        client.command(
            f"CREATE TABLE {database}.{name} ({cols}) ENGINE = MergeTree ORDER BY {ORDER_BY.get(name, 'tuple()')}"
        )
        # cast decimals/timestamps the same way the DDL does
        table = table.cast(pa.schema([pa.field(f.name, _arrow_target(f.type)) for f in table.schema]))
        client.insert_arrow(f"{database}.{name}", table)
        counts[name] = table.num_rows
    return counts


def _arrow_target(t: pa.DataType) -> pa.DataType:
    if pa.types.is_timestamp(t):
        return pa.timestamp("s")
    if pa.types.is_decimal(t):
        return pa.float64()
    return t


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://platform:platform@localhost:8123")
    p.add_argument("--src", type=Path, default=Path("./demo-data"))
    p.add_argument("--database", default="demo")
    a = p.parse_args()
    for name, n in load(a.url, a.src, a.database).items():
        print(f"{name:20s} {n:>12,d}")


if __name__ == "__main__":
    main()
