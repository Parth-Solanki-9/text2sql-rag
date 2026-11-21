"""Streamlit UI for SchemaRAG Text-to-SQL (powered by local Ollama)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.text2sql.config import PROJECT_ROOT, settings
from src.text2sql.llm.ollama_client import OLLAMA_MODELS, _is_ollama_running, _list_pulled_models
from src.text2sql.schema.ddl_parser import parse_ddl
from src.text2sql.schema.introspect import introspect_database
from src.text2sql.schema.models import DatabaseSchema
from src.text2sql.service import TextToSQLService
from src.text2sql.sql.executor import execute_read_only
from src.text2sql.sql.validator import validate_sql

DATA_DIR = PROJECT_ROOT / "data"
SCHEMA_FILE = DATA_DIR / "current_schema.json"

st.set_page_config(page_title="SchemaRAG | Text-to-SQL", page_icon="🧠", layout="wide")
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.6rem; padding-bottom: 2.5rem; max-width: 1280px;}
      .hero {padding: 1.25rem 1.4rem; border: 1px solid rgba(128,128,128,.25); border-radius: 14px; margin-bottom: 1rem;}
      .muted {opacity: .72; font-size: .92rem;}
      div[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.18); border-radius: 12px; padding: 12px;}
    </style>
    """,
    unsafe_allow_html=True,
)


def _load_saved_schema() -> DatabaseSchema | None:
    if SCHEMA_FILE.exists():
        try:
            return DatabaseSchema.from_dict(json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))
        except Exception:
            return None
    return None


def _store_schema(schema: DatabaseSchema) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCHEMA_FILE.write_text(json.dumps(schema.to_dict(), indent=2), encoding="utf-8")
    st.session_state.schema = schema
    st.session_state.last_result = None


if "schema" not in st.session_state:
    st.session_state.schema = _load_saved_schema()
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "last_error" not in st.session_state:
    st.session_state.last_error = None
if "db_url" not in st.session_state:
    st.session_state.db_url = settings.database_url

st.markdown(
    """
    <div class="hero">
      <h1 style="margin:0">🧠 SchemaRAG <span style="font-weight:400">Text-to-SQL</span></h1>
      <p class="muted" style="margin:.45rem 0 0">Ask questions in plain English. Retrieve the relevant schema, generate dialect-aware SQL with a local Ollama model, validate it, and optionally run it in read-only mode.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configuration")

    # Ollama status
    ollama_ok = _is_ollama_running()
    if ollama_ok:
        pulled = _list_pulled_models()
        if pulled:
            st.success(f"✅ Ollama running · {len(pulled)} model(s) pulled")
        else:
            st.warning("⚠️ Ollama running but no models pulled.\nRun: `ollama pull qwen2.5-coder:7b`")
    else:
        st.error("❌ Ollama not running.\nStart it: `ollama serve`")

    # Model selector — only show actually pulled models; fall back to recommended list
    pulled = _list_pulled_models() if ollama_ok else []
    model_options = pulled if pulled else OLLAMA_MODELS
    default_model = settings.ollama_model if settings.ollama_model in model_options else model_options[0]
    selected_model = st.selectbox(
        "Model",
        options=model_options,
        index=model_options.index(default_model) if default_model in model_options else 0,
        help="Pull more models with: ollama pull <model-name>",
    )
    st.caption("💡 Recommended: `qwen2.5-coder:7b` or `llama3.2:3b`")
    st.divider()

    st.subheader("Optional query execution")
    db_url = st.text_input(
        "Database URL",
        value=st.session_state.db_url,
        type="password",
        placeholder="mysql+pymysql://user:pass@localhost:3306/mydb",
        help="Used only when running 'Execute query'. Generation works from schema alone.",
    )
    st.session_state.db_url = db_url
    st.caption("Generation works from schema alone. A connection is only needed to execute SQL.")
    st.divider()
    st.caption("Safety: only one SELECT/CTE query is accepted. Results are capped at 200 rows by default.")

# ── Tabs ───────────────────────────────────────────────────────────────────────
setup_tab, ask_tab, guide_tab = st.tabs(["1 · Add database schema", "2 · Ask in natural language", "3 · How it works"])

with setup_tab:
    st.subheader("Bring your database schema")
    st.write("Upload a `.sql` file, paste `CREATE TABLE` statements, or connect to a database and introspect its catalog.")
    ddl_tab, connect_tab = st.tabs(["Upload / paste DDL", "Connect to a database"])
    with ddl_tab:
        dialect = st.selectbox("SQL dialect", ["sqlite", "mysql", "postgres", "tsql", "snowflake", "bigquery"], index=0)
        uploaded = st.file_uploader("Upload schema file (.sql)", type=["sql", "txt"])
        default_ddl = ""
        if uploaded is not None:
            try:
                default_ddl = uploaded.getvalue().decode("utf-8")
            except UnicodeDecodeError:
                st.error("The uploaded file must be UTF-8 encoded.")
        ddl_text = st.text_area(
            "Schema DDL",
            value=default_ddl,
            height=260,
            placeholder="CREATE TABLE customers (\n  customer_id INTEGER PRIMARY KEY,\n  name VARCHAR(100) NOT NULL\n);",
        )
        if st.button("Parse and index schema", type="primary", key="parse_ddl"):
            try:
                parsed_schema = parse_ddl(ddl_text, dialect=dialect)
                _store_schema(parsed_schema)
                st.success(f"Indexed {len(parsed_schema.tables)} tables.")
            except Exception as exc:
                st.error(str(exc))
    with connect_tab:
        connect_url = st.text_input(
            "SQLAlchemy connection URL",
            type="password",
            placeholder="mysql+pymysql://user:password@localhost:3306/database",
            key="connect_url",
        )
        schema_name = st.text_input("Schema name (optional)", placeholder="public")
        st.caption("Supported: MySQL (`mysql+pymysql://`), PostgreSQL (`postgresql+psycopg://`), SQLite (`sqlite:///path/to/db`)")
        if st.button("Connect and introspect", type="primary", key="introspect"):
            try:
                inspected = introspect_database(connect_url, schema_name or None)
                _store_schema(inspected)
                st.success(f"Successfully introspected {len(inspected.tables)} tables.")
            except Exception as exc:
                st.error(f"Could not introspect database: {exc}")

    schema = st.session_state.schema
    if schema:
        st.divider()
        st.subheader("Loaded schema")
        c1, c2, c3 = st.columns(3)
        c1.metric("Tables", len(schema.tables))
        c2.metric("Columns", sum(len(t.columns) for t in schema.tables))
        c3.metric("Foreign keys", sum(len(t.foreign_keys) for t in schema.tables))
        st.caption(f"Source: {schema.source} · Dialect: {schema.dialect}")
        with st.expander("Inspect schema details", expanded=True):
            for table in schema.tables:
                columns = ", ".join(f"`{c.name}` ({c.data_type})" for c in table.columns)
                st.markdown(f"**{table.name}**  \n{columns}")
                for fk in table.foreign_keys:
                    st.caption(f"↳ {', '.join(fk.columns)} → {fk.referenced_table}({', '.join(fk.referenced_columns)})")
        if st.button("Clear loaded schema", key="clear_schema"):
            st.session_state.schema = None
            st.session_state.last_result = None
            if SCHEMA_FILE.exists():
                SCHEMA_FILE.unlink()
            st.rerun()
    else:
        st.info("No schema is loaded yet. Add a DDL file or connect to a database above.")

with ask_tab:
    schema = st.session_state.schema
    if not schema:
        st.info("Start by adding a database schema in the first tab.")
    else:
        st.subheader("Ask your database")
        st.caption(f"Using {len(schema.tables)} indexed tables · {schema.dialect} dialect · model: `{selected_model}`")
        question = st.text_area(
            "What would you like to know?",
            height=100,
            placeholder="Example: Show the top 5 customers by total order value in 2025.",
        )
        examples = [
            "List the 10 most recent orders with customer names.",
            "Show total revenue by month for 2025.",
            "Find customers who have never placed an order.",
        ]
        chosen_example = st.selectbox("Or try a sample prompt", ["Choose an example…"] + examples)
        if chosen_example != "Choose an example…":
            question = chosen_example
        top_k = st.slider("Number of schema chunks to retrieve", min_value=2, max_value=12, value=settings.retrieval_top_k)

        if st.button("Generate SQL", type="primary", disabled=not question.strip()):
            if not ollama_ok:
                st.error("Ollama is not running. Start it with: `ollama serve`")
            else:
                with st.spinner(f"Generating SQL with {selected_model}…"):
                    try:
                        result = TextToSQLService(schema, model=selected_model).generate(question, top_k=top_k)
                        st.session_state.last_result = result
                        st.session_state.last_error = None
                    except Exception as exc:
                        st.session_state.last_error = str(exc)

        if st.session_state.get("last_error"):
            st.error(st.session_state.last_error)
            st.info(
                "💻 **Ollama troubleshooting:**\n\n"
                "1. Is Ollama running? Run: `ollama serve`\n"
                "2. Is the model pulled? Run: `ollama pull qwen2.5-coder:7b`\n"
                "3. Check status at [localhost:11434](http://localhost:11434)"
            )

        result = st.session_state.last_result
        if result:
            st.divider()
            if result.validation.is_valid:
                st.success("SQL passed the configured read-only and schema validation checks.")
            else:
                st.error("The SQL candidate did not pass validation. Review the errors before using it.")
            m1, m2, m3 = st.columns(3)
            m1.metric("Generation time", f"{result.latency_seconds:.2f}s")
            m2.metric("Generation attempts", result.attempts)
            m3.metric("Schema relevance", f"{result.retrieval_relevance * 100:.0f}/100")
            st.caption(f"Retrieval mode: {result.retrieval_mode}. Relevance is a heuristic, not a measured SQL accuracy score.")
            st.markdown("**Generated SQL**")
            st.code(result.sql, language="sql")
            st.download_button("Download SQL", data=result.sql, file_name="generated_query.sql", mime="text/plain")
            if result.explanation:
                st.markdown("**Explanation**")
                st.write(result.explanation)
            if result.assumptions:
                st.markdown("**Assumptions**")
                for assumption in result.assumptions:
                    st.markdown(f"- {assumption}")
            if result.validation.errors:
                st.markdown("**Validation errors**")
                for error in result.validation.errors:
                    st.error(error)
            if result.warnings:
                for warning in result.warnings:
                    st.warning(warning)
            with st.expander("Inspect retrieved schema context"):
                for chunk in result.retrieved_chunks:
                    st.markdown(f"**{chunk.table_name}** · relevance {chunk.score:.3f}")
                    st.code(chunk.content)
            st.markdown("**Optional read-only execution**")
            if not st.session_state.db_url:
                st.info("Enter a database URL in the sidebar to execute the generated query.")
            elif not result.validation.is_valid:
                st.warning("Execution is disabled because SQL validation failed.")
            elif st.button("Run query (read-only)", type="secondary"):
                try:
                    output = execute_read_only(st.session_state.db_url, result.sql, schema, max_rows=settings.max_rows)
                    st.success(f"Returned {output['row_count']} rows.")
                    if output["columns"]:
                        import pandas as pd
                        st.dataframe(pd.DataFrame(output["rows"], columns=output["columns"]), use_container_width=True)
                    if output["truncated"]:
                        st.caption(f"Results were truncated at {output['max_rows']} rows.")
                except Exception as exc:
                    st.error(f"Execution failed: {exc}")

with guide_tab:
    st.subheader("Pipeline overview")
    st.markdown(
        """
        1. **Schema onboarding** — parse uploaded DDL or introspect a live database with SQLAlchemy.
        2. **Schema chunking** — build one searchable document per table, including columns, primary keys and foreign-key links.
        3. **Hybrid retrieval** — local word and character TF-IDF with exact identifier boosts and FK-neighbour expansion. Fully offline.
        4. **Local LLM generation** — ask your Ollama model for a dialect-aware SQL query using only the retrieved schema context. No data leaves your machine.
        5. **Validation and repair** — parse the candidate with SQLGlot, reject unsafe operations and unknown tables, then retry once with validator feedback.
        6. **Optional execution** — execute one SELECT/CTE query with read-only protections and a bounded result size.

        **Privacy:** everything runs on your machine. No questions, schema, or data are sent to any external service.
        """
    )
    st.markdown("**Recommended Ollama models for SQL**")
    st.code("""ollama pull qwen2.5-coder:7b   # Best SQL quality (~4.5 GB)
ollama pull llama3.2:3b         # Fast & small (~2 GB)
ollama pull phi3:mini           # Very lightweight (~2.3 GB)""")
    st.markdown("**Example questions**")
    st.code("""Show customers with more than 3 orders.
What is the total revenue by product category?
Find the top 5 products by units sold in the previous month.
List customers who have not placed any orders.""")

st.markdown("<p class='muted' style='text-align:center;margin-top:2rem'>SchemaRAG · Local Ollama + TF-IDF RAG + SQLGlot + SQLAlchemy</p>", unsafe_allow_html=True)
