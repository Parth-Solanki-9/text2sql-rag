"""Evaluate generated SQL against the included SQLite benchmark.

Metrics:
- exact_match: normalized generated SQL text equals reference SQL text
- validation_rate: candidate passed the project's read-only/schema validator
- execution_accuracy: generated SQL returned the same rows as reference SQL

Execution comparison ignores row ordering, but preserves duplicate rows and values.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.text2sql.schema.ddl_parser import parse_ddl
from src.text2sql.service import TextToSQLService
from src.text2sql.sql.executor import execute_read_only

DB_PATH = ROOT / "data" / "demo.db"
SCHEMA_PATH = ROOT / "examples" / "schema.sql"
QUESTIONS_PATH = ROOT / "examples" / "evaluation_questions.json"


def _normal_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip().rstrip(";")).lower()


def _normalize_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    return str(value)


def _row_fingerprint(rows: list[list[Any]]) -> list[str]:
    encoded = [json.dumps([_normalize_value(v) for v in row], sort_keys=True, default=str) for row in rows]
    return sorted(encoded)


def _run_reference(sql: str) -> list[list[Any]]:
    connection = sqlite3.connect(DB_PATH)
    try:
        cursor = connection.execute(sql)
        return [list(row) for row in cursor.fetchall()]
    finally:
        connection.close()


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit("Demo database not found. Run: python scripts/init_demo_db.py")
    schema = parse_ddl(SCHEMA_PATH.read_text(encoding="utf-8"), dialect="sqlite")
    cases = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    service = TextToSQLService(schema)
    results = []
    for case in cases:
        item = {"id": case["id"], "question": case["question"], "generated_sql": None}
        try:
            generated = service.generate(case["question"])
            item["generated_sql"] = generated.sql
            item["valid"] = generated.validation.is_valid
            item["exact_match"] = _normal_sql(generated.sql) == _normal_sql(case["reference_sql"])
            item["attempts"] = generated.attempts
            item["latency_seconds"] = generated.latency_seconds
            if generated.validation.is_valid:
                actual = execute_read_only(
                    f"sqlite:///{DB_PATH.as_posix()}", generated.sql, schema, max_rows=5000
                )["rows"]
                expected = _run_reference(case["reference_sql"])
                item["execution_match"] = _row_fingerprint(actual) == _row_fingerprint(expected)
            else:
                item["execution_match"] = False
                item["validation_errors"] = generated.validation.errors
        except Exception as exc:
            item["valid"] = False
            item["exact_match"] = False
            item["execution_match"] = False
            item["error"] = str(exc)
        results.append(item)
        mark = "PASS" if item.get("execution_match") else "FAIL"
        print(f"[{mark}] {case['id']} · {case['question']}")

    total = len(results)
    summary = {
        "total_questions": total,
        "exact_match_rate": round(sum(bool(r.get("exact_match")) for r in results) / max(1, total), 4),
        "validation_rate": round(sum(bool(r.get("valid")) for r in results) / max(1, total), 4),
        "execution_accuracy": round(sum(bool(r.get("execution_match")) for r in results) / max(1, total), 4),
        "average_latency_seconds": round(
            sum(float(r.get("latency_seconds", 0)) for r in results) / max(1, total), 3
        ),
    }
    report = {"summary": summary, "results": results}
    output_path = ROOT / "data" / "evaluation_report.json"
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\nEvaluation summary")
    print(json.dumps(summary, indent=2))
    print(f"\nDetailed report saved to: {output_path}")
    print("Note: benchmark metrics apply only to these questions and this sample database.")


if __name__ == "__main__":
    main()
