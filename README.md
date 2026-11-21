# SchemaRAG — RAG-Powered Text-to-SQL with Gemini

A portfolio-ready Python application that converts natural-language questions into SQL grounded in a user-provided database schema. It uses Gemini for SQL generation, Gemini Embeddings for semantic retrieval (with a local TF-IDF fallback), SQLGlot for SQL parsing and safety checks, SQLAlchemy for schema introspection and optional read-only execution, and Streamlit/FastAPI for the user interfaces.

> **Important:** Generated SQL is a candidate, not a guarantee. Always review it before using it against important data. The application blocks common write/DDL operations and applies read-only execution protections, but a dedicated database account with read-only privileges is still strongly recommended.

## Features

- **Schema onboarding:** paste or upload SQL DDL, or introspect a live database through SQLAlchemy.
- **RAG schema retrieval:** one searchable document per table containing columns, types, primary keys and foreign-key relationships.
- **Hybrid retrieval:** Gemini dense embeddings (`gemini-embedding-001`) + word/character TF-IDF and exact-identifier boosts. If embeddings are unavailable, local TF-IDF retrieval still works.
- **Gemini SQL generation:** dialect-aware prompts, strict JSON output, low-temperature generation and schema-grounding instructions.
- **Validation and repair:** SQLGlot parsing, one-statement enforcement, SELECT/CTE-only policy, unknown-table checks and one automatic repair attempt.
- **Optional read-only execution:** bounded result sets, SQLite `query_only`, PostgreSQL read-only transactions and MySQL read-only session transactions.
- **Two interfaces:** Streamlit app for users and FastAPI endpoints for integration.
- **Evaluation harness:** exact-match rate, validation rate, execution accuracy and latency on 10 included benchmark questions.
- **Tests:** parser, schema serialization, retrieval, query safety and read-only execution tests.

## Architecture

```text
Natural-language question
          |
          v
   SchemaRAG pipeline <------ Uploaded DDL / SQLAlchemy introspection
          |                              |
          v                              v
  Hybrid schema retriever          Schema document builder
  - Gemini embeddings                    - table chunks
  - TF-IDF fallback                      - columns / PK / FK
  - identifier matching
  - FK-neighbour expansion
          |
          v
  Relevant schema context
          |
          v
     Gemini Flash
          |
          v
 Candidate SQL + explanation
          |
          v
 SQLGlot validation + schema checks
          |
     invalid? ---- yes ----> Gemini repair (one retry)
          |
          v
    Validated SQL
          |
          v
 Optional read-only execution
```

### Why this is RAG

The schema is not blindly pasted into the prompt. It is transformed into table-level documents, indexed, and retrieved against each user question. The retrieved table definitions and their foreign-key neighbours form the context supplied to Gemini. Gemini Embeddings provide semantic retrieval; a local TF-IDF hybrid index is the fallback. This keeps schema retrieval inexpensive and avoids requiring a hosted vector database.

## Tech stack

| Layer | Technology |
|---|---|
| LLM | Google Gemini API through `google-genai` |
| Embeddings | `gemini-embedding-001` |
| RAG / retrieval | NumPy, scikit-learn TF-IDF, cosine similarity |
| SQL parsing | SQLGlot |
| DB catalog and execution | SQLAlchemy 2.x |
| UI | Streamlit |
| API | FastAPI + Uvicorn |
| Demo DB | SQLite |
| Tests | pytest |

## 1. Requirements

- Python 3.10 or newer (Python 3.11/3.12 recommended).
- A Google AI Studio Gemini API key. The project is configured for Gemini's free tier where the selected models are available to your account; free quotas and model access can change.
- Optional: PostgreSQL or MySQL database plus a read-only database user if you want live introspection/execution.

## 2. Setup (Windows PowerShell)

Open PowerShell in the extracted project folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks virtual-environment activation, use this for the current terminal only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Or install/run with the virtual environment's Python executable directly, without activating it:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 3. Add your Gemini API key

1. Open [Google AI Studio](https://aistudio.google.com/app/apikey) and create an API key.
2. Open the `.env` file in the project root.
3. Replace the placeholder:

```dotenv
GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
```

The default model settings are:

```dotenv
GEMINI_MODEL=gemini-3.8-flash
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
USE_GEMINI_EMBEDDINGS=true
```

You can change `GEMINI_MODEL` to another model enabled for your Google AI Studio project. The embedding vectors for an unchanged schema are cached under `data/embedding_cache/`; query embeddings are generated when the user asks a question. If embeddings fail or are disabled, local TF-IDF retrieval is used automatically.

**Never commit your real `.env` file or expose the API key in screenshots, GitHub, or a public repository.** `.gitignore` already excludes `.env`.

## 4. Run the Streamlit application

```powershell
streamlit run app.py
```

Open the local URL printed in the terminal (usually `http://localhost:8501`).

### Quick start with the included demo schema

1. Open the **Add database schema** tab.
2. Select `sqlite` as the dialect.
3. Upload `examples/schema.sql`, or copy its contents into the DDL box.
4. Click **Parse and index schema**.
5. Open **Ask in natural language** and try:
   - `Show total revenue for each product category.`
   - `List customers who have never placed an order.`
   - `Find the top 3 products by units sold.`
6. To execute the generated query against the included sample database, set the sidebar database URL to `sqlite:///data/demo.db`.

The sample database is included. To recreate it:

```powershell
python scripts/init_demo_db.py
```

## 5. Connect to your own database

You can either upload DDL or use a SQLAlchemy connection URL in the **Connect to a database** tab.

Examples:

```text
# SQLite
sqlite:///C:/path/to/your_database.db

# PostgreSQL (install psycopg driver from requirements)
postgresql+psycopg://readonly_user:password@localhost:5432/database_name

# MySQL (install PyMySQL driver from requirements)
mysql+pymysql://readonly_user:password@localhost:3306/database_name
```

Use a dedicated account with `SELECT` permission only. Avoid using your production/admin credentials. Database URLs contain passwords, so do not paste them into source code or commit them to Git.

## 6. Run the FastAPI backend

Start the API:

```powershell
uvicorn src.text2sql.api:app --reload
```

Open the interactive docs at `http://127.0.0.1:8000/docs`.

Available endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/v1/schema/ddl` | Load schema from DDL text |
| POST | `/v1/schema/connect` | Introspect database schema |
| GET | `/v1/schema` | View the active schema |
| POST | `/v1/query` | Generate SQL from a question |
| POST | `/v1/validate` | Validate a SQL candidate |
| POST | `/v1/execute` | Execute a validated query in read-only mode |

Example schema upload payload:

```json
{
  "dialect": "sqlite",
  "ddl": "CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT);"
}
```

Example generation payload:

```json
{
  "question": "How many customers are there?",
  "top_k": 6
}
```

## 7. Use the command line

```powershell
python -m src.text2sql.cli --ddl examples/schema.sql --dialect sqlite --question "Show the top 5 customers by total order value."
```

## 8. Evaluate accuracy

Create or reset the demo database:

```powershell
python scripts/init_demo_db.py
```

Run the benchmark (this sends 10 generation requests to Gemini):

```powershell
python scripts/evaluate.py
```

The script writes `data/evaluation_report.json` and prints:

- **Exact-match rate:** normalized generated SQL string equals the reference SQL string. This is strict and can mark semantically equivalent SQL as different.
- **Validation rate:** percentage of candidate queries passing the configured validator.
- **Execution accuracy:** percentage of generated queries returning the same rows as the reference SQL on the included sample database. Row order is ignored, duplicates are preserved.
- **Average latency:** average generation pipeline time per question.

These values are only measurements on the included 10-question benchmark and sample data. They are not a universal accuracy guarantee. Expand the benchmark with your own schemas, natural-language questions and reference SQL before quoting a metric on your resume.

Run the tests:

```powershell
python -m pytest -q
```

## Configuration reference

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | placeholder | Google AI Studio API key |
| `GEMINI_MODEL` | `gemini-3.8-flash` | SQL generation model |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Dense schema embedding model |
| `USE_GEMINI_EMBEDDINGS` | `true` | Use dense semantic retrieval when key is configured |
| `DEFAULT_SQL_DIALECT` | `sqlite` | Default SQL dialect |
| `DATABASE_URL` | demo SQLite | Optional default execution URL |
| `RETRIEVAL_TOP_K` | `6` | Initial number of retrieved schema chunks |
| `MAX_RESULT_ROWS` | `200` | Maximum rows returned by UI/API execution |
| `QUERY_TIMEOUT_SECONDS` | `15` | Query execution timeout where supported (1–120 seconds) |
| `MAX_REPAIR_ATTEMPTS` | `1` | Number of LLM repair attempts (capped at 2) |

## Security and limitations

- The validator accepts one read-only `SELECT`/CTE query and rejects common DML, DDL, admin commands, `SELECT INTO`, and locking clauses.
- SQLGlot performs dialect-aware parsing when installed. A conservative lexical fallback is used if SQLGlot is not installed; install `requirements.txt` for the full parser.
- Table references are checked against the uploaded/reflected schema. Column-level validation is not complete for every SQL dialect and complex CTE/alias combination.
- Read-only safeguards are defense in depth, not a replacement for database permissions. Use read-only credentials and avoid connecting this demo directly to sensitive production databases.
- Query results are capped, but a complex query can still be expensive. Apply database-level statement timeouts, resource limits and network controls for production deployments.
- DDL-only schema import supports common `CREATE TABLE` syntax. For vendor-specific DDL or complex constraints, use live SQLAlchemy introspection where possible.
- Gemini free-tier quotas, rate limits and model access vary by account and can change. The app displays API errors and does not silently claim successful generation.

## Resume-ready project description

**SchemaRAG — RAG-Based Natural Language to SQL System**  
Built a Python application that translates natural-language questions into schema-grounded SQL using Gemini. Implemented schema ingestion from DDL and live databases, semantic/hybrid retrieval over table and relationship metadata, dialect-aware prompt construction, SQLGlot validation, automatic repair, and read-only query execution through SQLAlchemy. Added Streamlit and FastAPI interfaces, a sample relational database, automated tests, and an execution-accuracy evaluation harness.

After you run the benchmark, add the actual result to a resume bullet, for example:

> Evaluated on a 10-query SQLite benchmark and achieved **[your measured execution accuracy]%** execution accuracy with **[your measured validation rate]%** SQL validation success.

Do not fill in the brackets until you have run the evaluation yourself.

## Official references

- [Gemini API models](https://ai.google.dev/gemini-api/docs/models)
- [Gemini API Python quickstart](https://ai.google.dev/gemini-api/docs/get-started)
- [Gemini Embeddings](https://ai.google.dev/gemini-api/docs/embeddings)
- [Gemini API pricing and free tier](https://ai.google.dev/gemini-api/docs/pricing)
- [SQLGlot](https://sqlglot.com/)
- [SQLAlchemy](https://docs.sqlalchemy.org/)
- [Streamlit](https://docs.streamlit.io/)
- [FastAPI](https://fastapi.tiangolo.com/)
