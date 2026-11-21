"""SQLAlchemy database catalog introspection."""
from __future__ import annotations

from sqlalchemy import create_engine, inspect

from .models import ColumnSchema, DatabaseSchema, ForeignKeySchema, TableSchema


def introspect_database(database_url: str, schema_name: str | None = None) -> DatabaseSchema:
    if not database_url or not database_url.strip():
        raise ValueError("A database connection URL is required.")
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    try:
        inspector = inspect(engine)
        table_names = inspector.get_table_names(schema=schema_name)
        if not table_names:
            raise ValueError("No tables were found in the selected database/schema.")
        tables: list[TableSchema] = []
        for table_name in table_names:
            raw_columns = inspector.get_columns(table_name, schema=schema_name)
            pk_columns = set((inspector.get_pk_constraint(table_name, schema=schema_name) or {}).get("constrained_columns") or [])
            columns = [
                ColumnSchema(
                    name=item["name"],
                    data_type=str(item.get("type", "UNKNOWN")),
                    nullable=bool(item.get("nullable", True)) and item["name"] not in pk_columns,
                    primary_key=item["name"] in pk_columns,
                    default=str(item["default"]) if item.get("default") is not None else None,
                )
                for item in raw_columns
            ]
            foreign_keys: list[ForeignKeySchema] = []
            for fk in inspector.get_foreign_keys(table_name, schema=schema_name):
                if fk.get("referred_table"):
                    foreign_keys.append(
                        ForeignKeySchema(
                            columns=list(fk.get("constrained_columns") or []),
                            referenced_table=fk["referred_table"],
                            referenced_columns=list(fk.get("referred_columns") or []),
                            name=fk.get("name"),
                        )
                    )
            tables.append(
                TableSchema(
                    name=table_name,
                    columns=columns,
                    primary_key=list(pk_columns),
                    foreign_keys=foreign_keys,
                )
            )
        sqlglot_dialects = {"postgresql": "postgres", "mariadb": "mysql", "mssql": "tsql"}
        dialect = sqlglot_dialects.get(engine.dialect.name, engine.dialect.name)
        return DatabaseSchema(dialect=dialect, tables=tables, source="Database introspection")
    finally:
        engine.dispose()
