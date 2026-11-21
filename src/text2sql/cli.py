"""Command-line entry point for one-shot Text-to-SQL generation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .schema.ddl_parser import parse_ddl
from .service import TextToSQLService


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SQL from a natural-language question and a schema file.")
    parser.add_argument("--ddl", required=True, help="Path to a .sql file containing CREATE TABLE statements")
    parser.add_argument("--question", required=True, help="Natural-language question")
    parser.add_argument("--dialect", default="sqlite", help="SQL dialect (sqlite, postgres, mysql, etc.)")
    parser.add_argument("--top-k", type=int, default=6, help="Number of schema chunks to retrieve")
    args = parser.parse_args()
    ddl_path = Path(args.ddl)
    if not ddl_path.exists():
        raise SystemExit(f"DDL file not found: {ddl_path}")
    schema = parse_ddl(ddl_path.read_text(encoding="utf-8"), dialect=args.dialect)
    result = TextToSQLService(schema).generate(args.question, top_k=args.top_k)
    print("\nGenerated SQL\n--------------")
    print(result.sql)
    print("\nValidation:", "PASS" if result.validation.is_valid else "FAIL")
    for error in result.validation.errors:
        print("-", error)
    if result.explanation:
        print("\nExplanation:", result.explanation)
    if result.assumptions:
        print("Assumptions:")
        for assumption in result.assumptions:
            print("-", assumption)


if __name__ == "__main__":
    main()
