import sqlite3
from pathlib import Path

import pytest

from src.text2sql.schema.ddl_parser import parse_ddl
from src.text2sql.sql.executor import execute_read_only

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = parse_ddl((ROOT / "examples" / "schema.sql").read_text(encoding="utf-8"), "sqlite")


def test_executor_returns_rows_and_caps_results(tmp_path: Path):
    db_path = tmp_path / "sample.db"
    connection = sqlite3.connect(db_path)
    connection.executescript((ROOT / "examples" / "schema.sql").read_text(encoding="utf-8"))
    connection.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)",
        [(1, "A", "a@example.com", "Vadodara", "Gujarat", "2025-01-01"),
         (2, "B", "b@example.com", "Surat", "Gujarat", "2025-01-02")],
    )
    connection.commit()
    connection.close()
    result = execute_read_only(f"sqlite:///{db_path.as_posix()}", "SELECT name FROM customers ORDER BY name", SCHEMA, max_rows=1)
    assert result["row_count"] == 1
    assert result["truncated"] is True


def test_executor_rejects_write_queries(tmp_path: Path):
    db_path = tmp_path / "sample.db"
    connection = sqlite3.connect(db_path)
    connection.executescript((ROOT / "examples" / "schema.sql").read_text(encoding="utf-8"))
    connection.commit()
    connection.close()
    with pytest.raises(ValueError):
        execute_read_only(f"sqlite:///{db_path.as_posix()}", "DELETE FROM customers", SCHEMA)
