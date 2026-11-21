# Architecture Notes

## Schema ingestion

`schema/ddl_parser.py` handles common `CREATE TABLE` definitions for schema-only onboarding. `schema/introspect.py` uses SQLAlchemy Inspector to read tables, columns, primary keys and foreign keys from a live database.

## Retrieval

`retrieval/hybrid.py` creates one document per table. It combines:

- Gemini dense embeddings (document and query tasks) for semantic similarity;
- word-level and character-level TF-IDF similarities for exact identifiers and spelling variations;
- boosts for exact table/column identifier overlap;
- foreign-key neighbour expansion to provide likely join context.

Schema embeddings are cached in `data/embedding_cache` using a content fingerprint. If embedding access is unavailable, local sparse retrieval remains operational.

## Generation and correction

`service.py` supplies only the retrieved schema context to Gemini and asks for strict JSON containing SQL, a short explanation, assumptions and notes. The validator parses the SQL and checks that the query is read-only and uses known physical tables. On a failed validation, one correction prompt includes the validation errors and previous SQL.

## Execution boundary

`sql/executor.py` is deliberately separate from generation. The user must configure a database URL to run a candidate. It validates the query again, configures read-only connection behavior, fetches at most the configured row limit, and serializes results for display/API response.

## Evaluation

`scripts/evaluate.py` runs the same natural-language test questions against Gemini, compares generated output with reference SQL, and checks result equivalence on the included sample data. This gives a reproducible, task-specific measurement rather than a claimed general accuracy rate.
