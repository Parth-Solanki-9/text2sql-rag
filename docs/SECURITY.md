# Security Notes

This repository is an educational/portfolio application. Do not treat it as a hardened production data-access gateway.

1. Keep Gemini API keys and database passwords in local environment variables / `.env`; never commit real secrets.
2. Use a dedicated database account with SELECT-only permissions. Do not connect an administrator account.
3. The SQL validator rejects multiple statements and common write, DDL, administrative and locking operations. SQL parsing and table checks reduce risk but cannot prove a query is harmless.
4. SQLite execution sets `PRAGMA query_only = ON` and a progress-handler timeout. PostgreSQL uses read-only transactions and `statement_timeout`. MySQL uses a session execution-time limit. Verify driver/database behavior on the target server.
5. Apply statement timeouts and resource governance in the database itself. The application row cap only limits the number of rows fetched into the UI.
6. The question and retrieved schema context are sent to Gemini. Avoid putting secrets, personal information or sensitive comments in schema descriptions.
7. Review generated SQL before running it. Functions, views, custom operators and database extensions may have side effects that are not detectable by a generic SQL validator.
