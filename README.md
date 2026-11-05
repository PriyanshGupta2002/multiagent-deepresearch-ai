# DeepResearch AI

DeepResearch AI is a FastAPI backend for running multi-agent research jobs. It
stores research, generated reports, tasks, and sources in PostgreSQL, uses Redis
and ARQ to run research jobs in the background, and streams progress through
server-sent events (SSE). Users can explicitly save completed reports to a
personal library; saved reports reference the original research and do not copy
its content.

## What you'll need

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL
- Redis
- An OpenRouter API key for language-model calls
- A Tavily API key for web search

## Local setup

### 1. Install dependencies

```bash
uv sync --group dev
```

### 2. Configure environment variables

Create a `.env` file in the project root. It is git-ignored; do not commit
secrets.

```dotenv
# Required: use PostgreSQL with the asyncpg driver.
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/deepresearch

# Required by the test setup. Use a separate database from DATABASE_URL.
TEST_DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/deepresearch_test

# Required. Generate a unique local key, for example with: openssl rand -hex 32
SECRET_KEY=replace-with-a-long-random-secret

# Required by the research agents.
OPENROUTER_API_KEY=replace-with-your-openrouter-key
TAVILY_API_KEY=replace-with-your-tavily-key

# Optional; defaults shown.
REDIS_URL=redis://localhost:6379/0
FRONTEND_URL=http://localhost:3000
DEBUG=false
API_V1_PREFIX=/api/v1
APP_NAME=DeepResearch AI
APP_VERSION=1.0.0
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
COOKIE_SECURE=false
COOKIE_SAMESITE=lax
```

Start PostgreSQL and Redis using your preferred local installation. Create both
databases (for example, `createdb deepresearch` and
`createdb deepresearch_test`) before applying migrations.

### 3. Apply database migrations

Apply the current schema to the development database configured by
`DATABASE_URL`:

```bash
uv run alembic upgrade head
```

The test database needs the same schema. Apply migrations to it by temporarily
setting `DATABASE_URL` to the test database URL:

```bash
DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5432/deepresearch_test" \
  uv run alembic upgrade head
```

Replace the example connection strings with your own values. The test setup
requires `TEST_DATABASE_URL` and refuses to run if it points to the same
database as `DATABASE_URL`.

### 4. Start the API and worker

Run these in separate terminals, from the project root:

```bash
uv run uvicorn app.main:app --reload
```

```bash
uv run arq app.worker.WorkerSettings
```

The API is available at `http://localhost:8000`. Interactive API
documentation is at `http://localhost:8000/docs`; the health endpoint is
`http://localhost:8000/health`. Keep Redis and both API dependencies available
while developing: the API connects to Redis during startup, and research jobs
are processed by the ARQ worker.

## API overview

All versioned routes use the `/api/v1` prefix by default. Authentication uses
HTTP-only cookies set by the login and refresh endpoints. For browser clients,
configure `FRONTEND_URL` to the frontend origin.

### Authentication

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/auth/register` | Create an account |
| `POST` | `/api/v1/auth/login` | Sign in and set authentication cookies |
| `POST` | `/api/v1/auth/refresh` | Refresh the session cookies |
| `POST` | `/api/v1/auth/logout` | Revoke the session and clear cookies |
| `GET` | `/api/v1/auth/me` | Get the authenticated user |

Register with `email`, `full_name`, and `password` (at least 8 characters).
Use the cookies returned by login for authenticated routes.

### Research

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/research` | Queue research; returns `202 Accepted` |
| `GET` | `/api/v1/research` | List the current user's research (`page`, `limit`) |
| `GET` | `/api/v1/research/{research_id}` | Get research status and details |
| `GET` | `/api/v1/research/{research_id}/events` | Stream job events using SSE |
| `GET` | `/api/v1/research/{research_id}/report` | Get the completed report |
| `GET` | `/api/v1/research/{research_id}/tasks` | List research tasks |
| `GET` | `/api/v1/research/{research_id}/sources` | List research sources |
| `POST` | `/api/v1/research/{research_id}/cancel` | Cancel queued or running research |

Create a job with a query of 5–5,000 characters and optional depth
(`quick`, `standard`, or `comprehensive`; default `standard`):

```json
{
  "query": "What are the latest approaches to restoring coastal wetlands?",
  "depth": "standard"
}
```

Research runs asynchronously. A successful create response includes a research
ID and a status such as `queued`; poll the research endpoint or connect to its
`/events` endpoint to follow progress. Retrieve the report after the research
status is `completed`.

### Saved reports

Saving is explicit: completing research does not automatically add it to the
library. Each saved item belongs to the authenticated user and points to the
original research and report.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/saved-reports` | Save a completed report |
| `GET` | `/api/v1/saved-reports` | List saved reports |
| `GET` | `/api/v1/saved-reports/{research_id}/status` | Check whether a report is saved |
| `DELETE` | `/api/v1/saved-reports/{research_id}` | Unsave a report |

Save a report by sending its research ID:

```http
POST /api/v1/saved-reports
Content-Type: application/json

{"research_id":"550e8400-e29b-41d4-a716-446655440000"}
```

The response contains the saved association ID, research ID, original query
and depth, report creation time, and save time. A new save returns `201`;
repeating the request returns the existing record with `200`. The report must
belong to the current user, be completed, and have a generated report.

List reports with optional pagination and filters:

```http
GET /api/v1/saved-reports?page=1&limit=10&search=coastal&depth=standard
```

The response includes `items`, `total`, `page`, `limit`, `total_pages`, and
`has_more`. Each item includes a short preview from the actual report content.
Results are ordered newest saved first; `limit` is between 1 and 100.

The status endpoint returns `{"research_id":"…","is_saved":true}` (or
`false`). Deleting an already-unsaved report is safe and returns
`{"success":true,"research_id":"…","is_saved":false}`. Unsaving removes only
the user's saved association; it does not delete the research, report, tasks,
or sources.

### Error responses

Application errors use a consistent JSON shape:

```json
{
  "success": false,
  "message": "Research not found",
  "error_code": "RESEARCH_NOT_FOUND"
}
```

Unauthenticated requests return `401`; invalid request data returns `422`.
Research that does not exist or is not owned by the current user returns `404`.
Saving unfinished research or research without a generated report returns
`409`.

## Development

### Tests

Tests use `TEST_DATABASE_URL`, which must point to a dedicated database and
must already have the Alembic schema applied:

```bash
uv run pytest
```

Run a focused test module with:

```bash
uv run pytest tests/test_saved_reports.py -q
```

The test configuration checks that `TEST_DATABASE_URL` is distinct from
`DATABASE_URL` before running. Keep the two databases separate.

### Database migrations

Create a migration after changing SQLAlchemy models:

```bash
uv run alembic revision --autogenerate -m "describe the schema change"
```

Review generated migration code before applying it. Useful checks:

```bash
uv run alembic heads
uv run alembic check
```

`alembic check` compares model metadata with the database selected by
`DATABASE_URL`. Avoid running migrations or schema changes against a production
database during local development.

## Project layout

```text
app/
  agents/             Research-agent implementations
  core/               Settings, security, queue, and shared exceptions
  db/                 Async SQLAlchemy base, engine, and dependencies
  graph/              LangGraph workflow and nodes
  modules/
    auth/             Authentication routes, schemas, and services
    research/         Research routes, models, schemas, and services
    saved_reports/    Saved-report association and API
  worker.py           ARQ background worker
alembic/              Database migrations
tests/                Async API and worker tests
```

The API and application database access use asynchronous SQLAlchemy sessions.
The worker consumes jobs from the `deepresearch` Redis queue.