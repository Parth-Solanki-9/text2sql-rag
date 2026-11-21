from pathlib import Path

from src.text2sql.schema.ddl_parser import parse_ddl
from src.text2sql.sql.validator import validate_sql

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = parse_ddl((ROOT / "examples" / "schema.sql").read_text(encoding="utf-8"), "sqlite")


def test_select_is_accepted():
    result = validate_sql("SELECT name FROM customers WHERE state = 'Gujarat'", SCHEMA)
    assert result.is_valid


def test_drop_is_rejected():
    result = validate_sql("DROP TABLE customers", SCHEMA)
    assert not result.is_valid


def test_multiple_statements_are_rejected():
    result = validate_sql("SELECT * FROM customers; SELECT * FROM orders", SCHEMA)
    assert not result.is_valid


def test_unknown_table_is_rejected():
    result = validate_sql("SELECT * FROM secret_customer_table", SCHEMA)
    assert not result.is_valid


def test_keywords_inside_string_literal_are_not_treated_as_commands():
    result = validate_sql("SELECT 'DROP TABLE' AS message FROM customers", SCHEMA)
    assert result.is_valid
