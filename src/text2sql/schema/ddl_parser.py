"""A conservative CREATE TABLE DDL parser for common SQL dialects.

For production connections, SQLAlchemy reflection is preferred because it
reads the database's authoritative catalog. This parser supports portable
CREATE TABLE statements used for schema-only onboarding.
"""
from __future__ import annotations

import re
from typing import Iterable

from .models import ColumnSchema, DatabaseSchema, ForeignKeySchema, TableSchema

_IDENTIFIER = r'(?:`[^`]+`|"[^"]+"|\[[^\]]+\]|[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*)'
_CREATE_RE = re.compile(
    rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?({_IDENTIFIER})\s*\(",
    re.IGNORECASE | re.DOTALL,
)


def _clean_identifier(value: str) -> str:
    value = value.strip()
    parts = re.split(r"\.(?=(?:[^`\"]|`[^`]*`|\"[^\"]*\")*$)", value)
    cleaned = []
    for part in parts:
        part = part.strip().strip('`"')
        if part.startswith("[") and part.endswith("]"):
            part = part[1:-1]
        cleaned.append(part)
    return ".".join(cleaned)


def _matching_close_paren(text: str, open_index: int) -> int:
    depth = 0
    quote: str | None = None
    i = open_index
    while i < len(text):
        char = text[i]
        if quote:
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 1
                else:
                    quote = None
        elif char in ("'", '"', '`'):
            quote = char
        elif char == "[":
            if quote is None:
                quote = "]"
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("Unclosed parenthesis in CREATE TABLE statement")


def _split_top_level(text: str) -> list[str]:
    items: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 1
                else:
                    quote = None
        elif char in ("'", '"', '`'):
            quote = char
        elif char == "[":
            quote = "]"
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            items.append(text[start:i].strip())
            start = i + 1
        i += 1
    tail = text[start:].strip()
    if tail:
        items.append(tail)
    return items


def _strip_comments(ddl: str) -> str:
    # Keep quoted strings intact while removing SQL line/block comments.
    ddl = re.sub(r"/\*.*?\*/", " ", ddl, flags=re.DOTALL)
    return re.sub(r"(?m)^\s*--.*$", " ", ddl)


def _extract_statements(ddl: str) -> Iterable[str]:
    # Semicolons inside string literals are uncommon in schema DDL; splitting
    # statements here keeps the parser dependency-free and predictable.
    for statement in ddl.split(";"):
        if statement.strip():
            yield statement.strip()


def _parse_column(definition: str) -> ColumnSchema | None:
    match = re.match(rf"^({_IDENTIFIER})\s+(.+)$", definition.strip(), re.DOTALL)
    if not match:
        return None
    name = _clean_identifier(match.group(1))
    rest = match.group(2).strip()
    # Type ends at a top-level constraint keyword, preserving multiword types.
    constraint = re.search(
        r"\s+(?:NOT\s+NULL|NULL\b|DEFAULT\b|PRIMARY\s+KEY|UNIQUE\b|REFERENCES\b|CHECK\s*\(|COLLATE\b|GENERATED\b|AUTO_INCREMENT\b)",
        rest,
        re.IGNORECASE,
    )
    data_type = (rest[: constraint.start()] if constraint else rest).strip().rstrip(",")
    # Some definitions start with a type followed by comments/options; this is
    # intentionally descriptive, not a full grammar/type normalizer.
    if not data_type:
        data_type = rest.split()[0]
    is_pk = bool(re.search(r"\bPRIMARY\s+KEY\b", rest, re.IGNORECASE))
    nullable = not bool(re.search(r"\bNOT\s+NULL\b", rest, re.IGNORECASE)) and not is_pk
    default_match = re.search(r"\bDEFAULT\s+(.+?)(?=\s+(?:NOT\s+NULL|PRIMARY\s+KEY|UNIQUE|REFERENCES|CHECK)\b|$)", rest, re.IGNORECASE)
    default = default_match.group(1).strip() if default_match else None
    return ColumnSchema(name=name, data_type=data_type or "UNKNOWN", nullable=nullable, primary_key=is_pk, default=default)


def parse_ddl(ddl: str, dialect: str = "sqlite") -> DatabaseSchema:
    if not ddl or not ddl.strip():
        raise ValueError("Please provide SQL DDL containing at least one CREATE TABLE statement.")
    cleaned = _strip_comments(ddl)
    tables: list[TableSchema] = []
    for statement in _extract_statements(cleaned):
        match = _CREATE_RE.search(statement)
        if not match:
            continue
        table_name = _clean_identifier(match.group(1)).split(".")[-1]
        open_index = statement.find("(", match.start())
        close_index = _matching_close_paren(statement, open_index)
        body = statement[open_index + 1 : close_index]
        table = TableSchema(name=table_name)
        table_level_fks: list[ForeignKeySchema] = []
        for part in _split_top_level(body):
            upper = part.lstrip().upper()
            fk_match = re.search(
                rf"FOREIGN\s+KEY\s*\((.*?)\)\s*REFERENCES\s+({_IDENTIFIER})\s*\((.*?)\)",
                part,
                re.IGNORECASE | re.DOTALL,
            )
            if fk_match:
                fk_columns = [_clean_identifier(x) for x in _split_top_level(fk_match.group(1))]
                ref_columns = [_clean_identifier(x) for x in _split_top_level(fk_match.group(3))]
                table_level_fks.append(
                    ForeignKeySchema(
                        columns=fk_columns,
                        referenced_table=_clean_identifier(fk_match.group(2)).split(".")[-1],
                        referenced_columns=ref_columns,
                    )
                )
                continue
            if upper.startswith(("CONSTRAINT ", "PRIMARY KEY", "UNIQUE", "CHECK", "FOREIGN KEY")):
                pk_match = re.search(r"PRIMARY\s+KEY\s*\((.*?)\)", part, re.IGNORECASE | re.DOTALL)
                if pk_match:
                    table.primary_key = [_clean_identifier(x) for x in _split_top_level(pk_match.group(1))]
                continue
            column = _parse_column(part)
            if column:
                table.columns.append(column)
                if column.primary_key:
                    table.primary_key.append(column.name)
                inline_fk = re.search(
                    rf"REFERENCES\s+({_IDENTIFIER})\s*\((.*?)\)", part,
                    re.IGNORECASE | re.DOTALL,
                )
                if inline_fk:
                    table_level_fks.append(
                        ForeignKeySchema(
                            columns=[column.name],
                            referenced_table=_clean_identifier(inline_fk.group(1)).split(".")[-1],
                            referenced_columns=[_clean_identifier(x) for x in _split_top_level(inline_fk.group(2))],
                        )
                    )
        if table.primary_key:
            pk_set = {name.lower() for name in table.primary_key}
            for column in table.columns:
                if column.name.lower() in pk_set:
                    column.primary_key = True
                    column.nullable = False
        table.foreign_keys.extend(table_level_fks)
        if table.columns:
            tables.append(table)
    if not tables:
        raise ValueError("No supported CREATE TABLE statements were found in the supplied DDL.")
    names = [table.name.lower() for table in tables]
    if len(names) != len(set(names)):
        raise ValueError("The DDL contains duplicate table names. Use unique table names or schema-qualified DDL.")
    return DatabaseSchema(dialect=dialect.lower(), tables=tables, source="DDL")
