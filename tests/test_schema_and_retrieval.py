from pathlib import Path

from src.text2sql.retrieval.hybrid import HybridSchemaRetriever
from src.text2sql.schema.ddl_parser import parse_ddl

ROOT = Path(__file__).resolve().parents[1]


def _schema():
    return parse_ddl((ROOT / "examples" / "schema.sql").read_text(encoding="utf-8"), "sqlite")


def test_ddl_parser_extracts_tables_columns_and_foreign_keys():
    schema = _schema()
    table_map = schema.table_map()
    assert {"customers", "orders", "products", "order_items"}.issubset(table_map)
    assert "customer_id" in table_map["orders"].column_names()
    assert table_map["orders"].foreign_keys[0].referenced_table == "customers"


def test_schema_round_trip_serialization():
    schema = _schema()
    from src.text2sql.schema.models import DatabaseSchema

    restored = DatabaseSchema.from_dict(schema.to_dict())
    assert restored.to_prompt_text() == schema.to_prompt_text()


def test_retriever_surfaces_product_tables_for_sales_question():
    retriever = HybridSchemaRetriever(_schema())
    chunks = retriever.retrieve("total revenue by product category", top_k=3)
    names = {chunk.table_name for chunk in chunks}
    assert "products" in names
    assert "categories" in names or "order_items" in names
