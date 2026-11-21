"""Bounded, read-only SQL execution helper."""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..config import settings
from ..schema.models import DatabaseSchema
from .validator import validate_sql


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def execute_read_only(
    database_url: str,
    sql: str,
    schema: DatabaseSchema,
    max_rows: int = 200,
) -> dict[str, Any]:
    if not database_url:
        raise ValueError("Set a database URL before executing a query.")
    if max_rows < 1 or max_rows > 5000:
        raise ValueError("max_rows must be between 1 and 5000.")
    validation = validate_sql(sql, schema)
    if not validation.is_valid:
        raise ValueError("Query rejected: " + " ".join(validation.errors))

    timeout_seconds = max(1, min(settings.query_timeout_seconds, 120))
    engine: Engine = create_engine(database_url, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as connection:
            # SQLite has a per-connection read-only switch and a progress
            # callback that can abort long-running virtual-machine operations.
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("PRAGMA query_only = ON")
                raw_connection = connection.connection.driver_connection
                deadline = time.monotonic() + timeout_seconds
                raw_connection.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
                connection.commit()  # PRAGMA starts an implicit SQLAlchemy transaction.
            elif engine.dialect.name in {"mysql", "mariadb"}:
                # Session-scoped settings are cleared when this connection closes.
                connection.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
                if engine.dialect.name == "mysql":
                    connection.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME={timeout_seconds * 1000}")
                else:
                    connection.exec_driver_sql(f"SET SESSION max_statement_time={timeout_seconds}")
                connection.commit()
            with connection.begin():
                if engine.dialect.name == "postgresql":
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                    connection.exec_driver_sql(f"SET LOCAL statement_timeout = '{timeout_seconds * 1000}ms'")
                result = connection.execute(text(validation.normalized_sql))
                columns = list(result.keys())
                rows = result.fetchmany(max_rows + 1)
                truncated = len(rows) > max_rows
                rows = rows[:max_rows]
                safe_rows = [[_json_safe(value) for value in row] for row in rows]
                return {
                    "columns": columns,
                    "rows": safe_rows,
                    "row_count": len(safe_rows),
                    "truncated": truncated,
                    "max_rows": max_rows,
                    "read_only": True,
                }
    finally:
        engine.dispose()
