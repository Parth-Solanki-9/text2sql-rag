"""Read-only SQL validation, with SQLGlot parsing when available."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..schema.models import DatabaseSchema


_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|MERGE|GRANT|REVOKE|"
    r"ATTACH|DETACH|PRAGMA|VACUUM|COPY|CALL|EXEC|EXECUTE|LOAD|INSTALL|EXPORT|IMPORT)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ValidationResult:
    is_valid: bool
    normalized_sql: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parser: str = "fallback"
    referenced_tables: list[str] = field(default_factory=list)


def clean_sql(raw_sql: str) -> str:
    sql = (raw_sql or "").strip()
    sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\s*```$", "", sql)
    sql = re.sub(r"^\s*SQL\s*:\s*", "", sql, flags=re.IGNORECASE)
    return sql.strip().rstrip(";").strip()


def _mask_literals_and_comments(sql: str) -> str:
    # Preserve token positions while masking quoted values and comments.
    pattern = re.compile(r"(--[^\n]*|/\*[\s\S]*?\*/|'(?:''|[^'])*')")
    return pattern.sub(lambda m: " " * len(m.group(0)), sql)


def _fallback_validate(sql: str, schema: DatabaseSchema) -> ValidationResult:
    errors: list[str] = []
    masked = _mask_literals_and_comments(sql)
    if not re.match(r"^\s*(SELECT|WITH)\b", masked, re.IGNORECASE):
        errors.append("Only read-only SELECT statements (including WITH/CTE queries) are allowed.")
    if ";" in masked:
        errors.append("Multiple SQL statements are not allowed. Submit one query at a time.")
    if _FORBIDDEN.search(masked):
        errors.append("The query contains a write, DDL, administrative, or unsafe SQL keyword.")
    if re.search(r"\bSELECT\b[\s\S]*?\bINTO\b", masked, re.IGNORECASE):
        errors.append("SELECT INTO is not allowed because it writes data.")
    if re.search(r"\bFOR\s+(UPDATE|SHARE)\b", masked, re.IGNORECASE):
        errors.append("Locking clauses are not allowed in read-only mode.")

    known_tables = {table.name.lower() for table in schema.tables}
    cte_names = {name.lower() for name in re.findall(r"(?:WITH|,)\s*([A-Za-z_][\w$]*)\s+AS\s*\(", masked, re.IGNORECASE)}
    found: list[str] = []
    for match in re.finditer(r"\b(?:FROM|JOIN)\s+([`\"\[]?[\w.$]+[`\"\]]?)", masked, re.IGNORECASE):
        name = match.group(1).strip('`"[]').split(".")[-1].lower()
        if name in known_tables:
            found.append(name)
        elif name not in cte_names and name not in {"select", "values"}:
            errors.append(f"Table '{name}' is not present in the uploaded schema.")
    if not found and not errors:
        errors.append("No table reference could be identified. Check the FROM clause.")
    return ValidationResult(
        is_valid=not errors,
        normalized_sql=sql,
        errors=errors,
        warnings=["SQLGlot is not installed; fallback lexical validation was used."],
        parser="fallback",
        referenced_tables=sorted(set(found)),
    )


def validate_sql(raw_sql: str, schema: DatabaseSchema) -> ValidationResult:
    sql = clean_sql(raw_sql)
    if not sql:
        return ValidationResult(False, sql, ["The model returned an empty SQL query."])

    try:
        import sqlglot
        from sqlglot import exp
    except ImportError:
        return _fallback_validate(sql, schema)

    errors: list[str] = []
    warnings: list[str] = []
    try:
        parsed = sqlglot.parse(sql, read=schema.dialect)
        parsed = [node for node in parsed if node is not None]
        if len(parsed) != 1:
            errors.append("Exactly one SQL statement is allowed.")
        if parsed:
            root = parsed[0]
            # SELECT, UNION, INTERSECT and EXCEPT are query roots. A WITH clause
            # is represented as an attribute on the query root by SQLGlot.
            if root.key not in {"select", "union", "intersect", "except"}:
                errors.append("Only read-only SELECT queries are allowed.")
            if any(isinstance(node, exp.Into) for node in root.walk()):
                errors.append("SELECT INTO is not allowed because it writes data.")
            if any(isinstance(node, exp.Lock) for node in root.walk()):
                errors.append("Locking clauses are not allowed in read-only mode.")
            cte_names = {
                cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)
                if cte.alias_or_name
            }
            known_tables = {table.name.lower() for table in schema.tables}
            referenced = []
            for table_node in root.find_all(exp.Table):
                name = table_node.name.lower()
                if not name or name in cte_names:
                    continue
                if name not in known_tables:
                    errors.append(f"Table '{table_node.name}' is not present in the uploaded schema.")
                else:
                    referenced.append(name)
            if not referenced and not errors:
                errors.append("No known physical table was referenced by the query.")
            return ValidationResult(
                is_valid=not errors,
                normalized_sql=sql,
                errors=errors,
                warnings=warnings,
                parser="sqlglot",
                referenced_tables=sorted(set(referenced)),
            )
    except Exception as exc:
        errors.append(f"SQL parser rejected the query: {exc}")
    return ValidationResult(False, sql, errors, warnings, parser="sqlglot")
