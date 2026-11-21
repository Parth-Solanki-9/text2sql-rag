"""End-to-end RAG pipeline: retrieve schema -> generate SQL -> validate -> repair."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import settings
from .llm.ollama_client import OllamaSQLGenerator, LLMOutput
from .retrieval.hybrid import HybridSchemaRetriever, RetrievedChunk
from .schema.models import DatabaseSchema
from .sql.validator import ValidationResult, validate_sql


@dataclass(slots=True)
class GenerationResult:
    question: str
    sql: str
    explanation: str
    assumptions: list[str]
    notes: list[str]
    validation: ValidationResult
    retrieved_chunks: list[RetrievedChunk]
    model: str
    attempts: int
    latency_seconds: float
    retrieval_relevance: float
    retrieval_mode: str
    warnings: list[str] = field(default_factory=list)


class TextToSQLService:
    def __init__(
        self,
        schema: DatabaseSchema,
        generator: OllamaSQLGenerator | None = None,
        model: str | None = None,
    ):
        self.schema = schema
        self.retriever = HybridSchemaRetriever(schema)
        self.generator = generator or OllamaSQLGenerator(
            model=model, base_url=settings.ollama_base_url
        )

    def _build_prompt(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        repair_feedback: list[str] | None = None,
        previous_sql: str | None = None,
    ) -> str:
        context = self.retriever.context_for(chunks)
        feedback = ""
        if repair_feedback:
            feedback = (
                "\nThe previous candidate did not pass validation. Fix all issues below."
                f"\nValidation errors: {repair_feedback}"
                f"\nPrevious SQL: {previous_sql}\n"
            )
        return f"""You are a senior database engineer specializing in accurate, safe text-to-SQL.

TASK
Convert the user's natural-language request into exactly one SQL query.

DATABASE DIALECT
{self.schema.dialect}

RETRIEVED DATABASE SCHEMA (authoritative; use only these objects)
{context}

USER QUESTION
{question}

RULES
1. Use only tables and columns present in the retrieved schema. Never invent identifiers.
2. Follow declared foreign-key relationships for joins. If a relationship is not declared, infer a join only when column names and semantics make it unambiguous; otherwise state the assumption.
3. Use dialect-correct date functions, string functions, quoting, LIMIT/TOP/FETCH syntax, and aggregation.
4. Select only columns needed to answer the question. Use clear aliases for calculated or aggregated fields.
5. Do not use INSERT, UPDATE, DELETE, MERGE, DDL, stored procedures, PRAGMA, SELECT INTO, locking clauses, or multiple statements.
6. Do not add a LIMIT unless the user asks for a limited result or the question asks for a sample/top-N.
7. For ambiguous wording, choose the most reasonable interpretation and record it in assumptions.
8. Return syntactically valid SQL and no markdown fences.
9. Return a strict JSON object with keys: sql (string), explanation (string), assumptions (array of strings), notes (array of strings).
10. Do not return chain-of-thought or hidden reasoning. Give only a brief explanation of what the query does.
{feedback}
JSON response:"""

    def generate(self, question: str, top_k: int | None = None) -> GenerationResult:
        question = question.strip()
        if not question:
            raise ValueError("Enter a natural-language question before generating SQL.")
        started = time.perf_counter()
        chunks = self.retriever.retrieve(question, top_k or settings.retrieval_top_k)
        output: LLMOutput = self.generator.generate(self._build_prompt(question, chunks))
        validation = validate_sql(output.sql, self.schema)
        attempts = 1
        max_repairs = max(0, min(settings.max_repair_attempts, 2))

        while not validation.is_valid and attempts <= max_repairs:
            output = self.generator.generate(
                self._build_prompt(
                    question,
                    chunks,
                    repair_feedback=validation.errors,
                    previous_sql=output.sql,
                )
            )
            validation = validate_sql(output.sql, self.schema)
            attempts += 1

        average_score = sum(chunk.score for chunk in chunks) / max(1, len(chunks))
        relevance = round(min(1.0, max(0.0, average_score * 2.5)), 3)
        warnings = list(validation.warnings)
        if self.retriever.retrieval_warning:
            warnings.append(self.retriever.retrieval_warning)
        if not validation.is_valid:
            warnings.append("Do not execute this candidate until the validation errors are resolved.")
        return GenerationResult(
            question=question,
            sql=validation.normalized_sql,
            explanation=output.explanation,
            assumptions=output.assumptions or [],
            notes=output.notes or [],
            validation=validation,
            retrieved_chunks=chunks,
            model=self.generator.model,
            attempts=attempts,
            latency_seconds=round(time.perf_counter() - started, 3),
            retrieval_relevance=relevance,
            retrieval_mode=self.retriever.retrieval_mode,
            warnings=warnings,
        )
