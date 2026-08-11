# Backend

FastAPI service for Document Copilot. Run every command from `backend/`.

## Setup

```bash
uv sync                 # install deps + editable `app` package
cp .env.example .env    # then fill in real values
```

`app/config.py` validates the env on import, so a missing or bad value fails at startup.

## Run the API

```bash
uv run uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000
- Health check: http://127.0.0.1:8000/health
- Interactive docs: http://127.0.0.1:8000/docs

Stop with `Ctrl+C`. `uv run python app/main.py` does the same thing.

## Dependencies

```bash
uv add <package>          # runtime dep
uv add --dev <package>    # dev-only dep
uv sync                   # match the venv to uv.lock
```

## Checks

```bash
uv run ruff check .       # lint
uv run ruff format .      # format
uv run pytest             # tests
```

## Migrations

Alembic owns the schema. `alembic/env.py` reads `DATABASE_URL` from `app/config.py`, so there is no connection string in `alembic.ini`.

```bash
uv run alembic upgrade head                    # apply
uv run alembic current                         # show applied revision
uv run alembic upgrade head --sql              # render SQL without connecting
uv run alembic revision --autogenerate -m "…"  # after changing models
```

Models live in `app/database/models/`, one table per module. Every model must be re-exported from `models/__init__.py` — autogenerate proposes dropping any table it cannot see.

`DATABASE_URL` must be a session-level connection: Supabase's direct connection, or the pooler on port **5432**. The transaction pooler (port 6543) cannot run DDL.

Autogenerate cannot infer RLS policies or the `vector` extension — add those to migrations by hand, and review every generated file before applying it.
