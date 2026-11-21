"""FastAPI interface for schema onboarding, text-to-SQL and safe execution."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import settings
from .schema.ddl_parser import parse_ddl
from .schema.introspect import introspect_database
from .schema.models import DatabaseSchema
from .service import TextToSQLService
from .sql.executor import execute_read_only
from .sql.validator import validate_sql

app = FastAPI(
    title="SchemaRAG Text-to-SQL API",
    description="Schema-grounded natural-language-to-SQL API powered by local Ollama and TF-IDF retrieval.",
    version="2.0.0",
)
_current_schema: DatabaseSchema | None = None


class DDLRequest(BaseModel):
    ddl: str = Field(min_length=1, description="CREATE TABLE DDL statements")
    dialect: str = Field(default="sqlite", description="sqlite, mysql, postgres, etc.")


class ConnectRequest(BaseModel):
    database_url: str = Field(min_length=1)
    schema_name: str | None = None


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(default=6, ge=1, le=20)
    model: str | None = None


class ExecuteRequest(BaseModel):
    sql: str = Field(min_length=1)
    database_url: str | None = None
    max_rows: int = Field(default=200, ge=1, le=5000)


def _require_schema() -> DatabaseSchema:
    if _current_schema is None:
        raise HTTPException(status_code=409, detail="Upload or connect a database schema first.")
    return _current_schema


def _serialize_generation(result: Any) -> dict[str, Any]:
    return {
        "question": result.question,
        "sql": result.sql,
        "explanation": result.explanation,
        "assumptions": result.assumptions,
        "notes": result.notes,
        "validation": {
            "is_valid": result.validation.is_valid,
            "errors": result.validation.errors,
            "warnings": result.validation.warnings,
            "parser": result.validation.parser,
            "referenced_tables": result.validation.referenced_tables,
        },
        "retrieved_schema": [
            {"table": item.table_name, "score": item.score, "content": item.content}
            for item in result.retrieved_chunks
        ],
        "retrieval_relevance_heuristic": result.retrieval_relevance,
        "retrieval_mode": result.retrieval_mode,
        "model": result.model,
        "attempts": result.attempts,
        "latency_seconds": result.latency_seconds,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "SchemaRAG Text-to-SQL"}


@app.post("/v1/schema/ddl")
def upload_ddl(request: DDLRequest) -> dict[str, Any]:
    global _current_schema
    try:
        _current_schema = parse_ddl(request.ddl, request.dialect)
        return {"message": "Schema loaded successfully", "schema": _current_schema.to_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/schema/connect")
def connect_schema(request: ConnectRequest) -> dict[str, Any]:
    global _current_schema
    try:
        _current_schema = introspect_database(request.database_url, request.schema_name)
        return {"message": "Database schema introspected successfully", "schema": _current_schema.to_dict()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/schema")
def get_schema() -> dict[str, Any]:
    return _require_schema().to_dict()


@app.post("/v1/query")
def generate_query(request: QueryRequest) -> dict[str, Any]:
    schema = _require_schema()
    try:
        result = TextToSQLService(schema, model=request.model).generate(request.question, top_k=request.top_k)
        return _serialize_generation(result)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/validate")
def validate_query(request: ExecuteRequest) -> dict[str, Any]:
    result = validate_sql(request.sql, _require_schema())
    return {
        "is_valid": result.is_valid,
        "errors": result.errors,
        "warnings": result.warnings,
        "parser": result.parser,
        "referenced_tables": result.referenced_tables,
    }


@app.post("/v1/execute")
def execute_query(request: ExecuteRequest) -> dict[str, Any]:
    schema = _require_schema()
    database_url = request.database_url or settings.database_url
    try:
        return execute_read_only(database_url, request.sql, schema, max_rows=request.max_rows)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
