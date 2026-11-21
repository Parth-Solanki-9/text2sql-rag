"""Local hybrid retriever over schema documents (word + character TF-IDF).

The sparse index is fully local — no API calls, no external vector database,
and fast for typical application schemas. Exact identifier boosts and FK-neighbour
expansion make SQL schema linking stronger.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ..schema.models import DatabaseSchema, TableSchema


@dataclass(slots=True)
class RetrievedChunk:
    table_name: str
    content: str
    score: float


def _tokens(text: str) -> set[str]:
    """Split snake_case / camelCase identifiers and ordinary words."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return {t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text) if len(t) > 1}


def _table_document(table: TableSchema) -> str:
    columns = "; ".join(
        f"{c.name} {c.data_type}"
        + (" primary key" if c.primary_key else "")
        + (" not null" if not c.nullable else "")
        for c in table.columns
    )
    relationships = "; ".join(
        f"{', '.join(fk.columns)} references {fk.referenced_table}({', '.join(fk.referenced_columns)})"
        for fk in table.foreign_keys
    )
    return (
        f"Table {table.name}. Columns: {columns}. "
        f"Primary key: {', '.join(table.primary_key) or 'not declared'}. "
        f"Foreign key relationships: {relationships or 'none declared'}. "
        f"Description: {table.description or 'not provided'}."
    )


class HybridSchemaRetriever:
    def __init__(self, schema: DatabaseSchema):
        if not schema.tables:
            raise ValueError("The schema contains no tables to index.")
        self.schema = schema
        self.tables = schema.tables
        self.documents = [_table_document(t) for t in self.tables]
        self.word_vectorizer = TfidfVectorizer(
            ngram_range=(1, 2), analyzer="word", sublinear_tf=True,
            lowercase=True, token_pattern=r"(?u)\b[\w$]+\b",
        )
        self.char_vectorizer = TfidfVectorizer(
            ngram_range=(2, 5), analyzer="char_wb", sublinear_tf=True, lowercase=True,
        )
        self.word_matrix = self.word_vectorizer.fit_transform(self.documents)
        self.char_matrix = self.char_vectorizer.fit_transform(self.documents)
        self._by_name = {t.name.lower(): t for t in self.tables}
        self.retrieval_mode = "hybrid-tfidf"
        self.retrieval_warning: str | None = None

    def retrieve(self, question: str, top_k: int = 6) -> list[RetrievedChunk]:
        if not question.strip():
            raise ValueError("Question cannot be empty.")
        q_words = self.word_vectorizer.transform([question])
        q_chars = self.char_vectorizer.transform([question])
        word_scores = cosine_similarity(q_words, self.word_matrix).ravel()
        char_scores = cosine_similarity(q_chars, self.char_matrix).ravel()
        query_tokens = _tokens(question)
        scores: list[float] = []
        for i, table in enumerate(self.tables):
            score = 0.68 * float(word_scores[i]) + 0.32 * float(char_scores[i])
            if _tokens(table.name) & query_tokens:
                score += 0.20
            col_tokens = set().union(*(_tokens(c.name) for c in table.columns)) if table.columns else set()
            score += min(0.12, len(col_tokens & query_tokens) * 0.035)
            scores.append(score)

        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        selected: list[int] = order[: max(1, min(top_k, len(order)))]

        # Expand to FK-related tables so joins have full context
        selected_names = {self.tables[i].name.lower() for i in selected}
        related: set[str] = set()
        for idx in list(selected):
            for fk in self.tables[idx].foreign_keys:
                related.add(fk.referenced_table.lower())
            for other in self.tables:
                if any(fk.referenced_table.lower() == self.tables[idx].name.lower() for fk in other.foreign_keys):
                    related.add(other.name.lower())
        for name in sorted(related):
            if name not in selected_names and name in self._by_name:
                selected.append(next(i for i, t in enumerate(self.tables) if t.name.lower() == name))
                selected_names.add(name)
                if len(selected) >= top_k + 2:
                    break

        return [
            RetrievedChunk(
                table_name=self.tables[i].name,
                content=self.documents[i],
                score=round(scores[i], 4),
            )
            for i in selected
        ]

    def context_for(self, chunks: list[RetrievedChunk]) -> str:
        names = {c.table_name.lower() for c in chunks}
        relevant = [t for t in self.tables if t.name.lower() in names]
        subset = DatabaseSchema(dialect=self.schema.dialect, tables=relevant, source=self.schema.source)
        return subset.to_prompt_text()
