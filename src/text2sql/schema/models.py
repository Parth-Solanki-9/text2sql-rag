"""Typed schema objects shared by ingestion, retrieval and generation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ColumnSchema:
    name: str
    data_type: str = "UNKNOWN"
    nullable: bool = True
    primary_key: bool = False
    default: str | None = None
    description: str | None = None


@dataclass(slots=True)
class ForeignKeySchema:
    columns: list[str]
    referenced_table: str
    referenced_columns: list[str]
    name: str | None = None


@dataclass(slots=True)
class TableSchema:
    name: str
    columns: list[ColumnSchema] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKeySchema] = field(default_factory=list)
    description: str | None = None

    def column_names(self) -> set[str]:
        return {column.name.lower() for column in self.columns}


@dataclass(slots=True)
class DatabaseSchema:
    dialect: str
    tables: list[TableSchema]
    source: str = "DDL"

    def table_map(self) -> dict[str, TableSchema]:
        return {table.name.lower(): table for table in self.tables}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DatabaseSchema":
        tables: list[TableSchema] = []
        for raw_table in payload.get("tables", []):
            columns = [ColumnSchema(**item) for item in raw_table.get("columns", [])]
            foreign_keys = [ForeignKeySchema(**item) for item in raw_table.get("foreign_keys", [])]
            tables.append(
                TableSchema(
                    name=raw_table["name"],
                    columns=columns,
                    primary_key=list(raw_table.get("primary_key", [])),
                    foreign_keys=foreign_keys,
                    description=raw_table.get("description"),
                )
            )
        return cls(
            dialect=payload.get("dialect", "sqlite"),
            tables=tables,
            source=payload.get("source", "DDL"),
        )

    def to_prompt_text(self) -> str:
        """Compact, deterministic schema representation for LLM context."""
        lines = [f"Database dialect: {self.dialect}"]
        for table in self.tables:
            lines.append(f"TABLE {table.name}:")
            for column in table.columns:
                flags = []
                if column.primary_key:
                    flags.append("PRIMARY KEY")
                if not column.nullable:
                    flags.append("NOT NULL")
                suffix = f" [{', '.join(flags)}]" if flags else ""
                lines.append(f"  - {column.name} {column.data_type}{suffix}")
            for fk in table.foreign_keys:
                left = ", ".join(fk.columns)
                right = ", ".join(fk.referenced_columns)
                lines.append(f"  - FOREIGN KEY ({left}) REFERENCES {fk.referenced_table} ({right})")
        return "\n".join(lines)
