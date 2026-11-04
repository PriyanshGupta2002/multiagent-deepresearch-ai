import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_test_database_url = os.environ.get("TEST_DATABASE_URL")

if not _test_database_url:
    raise pytest.UsageError(
        "TEST_DATABASE_URL must be set to a dedicated test database before running pytest."
    )

if "app.core.config" in sys.modules or "app.db.session" in sys.modules:
    raise pytest.UsageError(
        "Application settings/database modules were imported before "
        "TEST_DATABASE_URL was configured."
    )


def _parse_url(value: str, name: str) -> URL:
    try:
        return make_url(value)
    except (ArgumentError, TypeError) as exc:
        raise pytest.UsageError(f"{name} must be a valid SQLAlchemy database URL.") from exc


def _database_identity(url: URL) -> tuple[str, str | None, int | None, str | None]:
    backend = url.get_backend_name()

    if backend == "sqlite":
        database = url.database
        if database not in (None, "", ":memory:"):
            database = str(Path(database).expanduser().resolve())
        return backend, None, None, database

    default_ports = {
        "mariadb": 3306,
        "mssql": 1433,
        "mysql": 3306,
        "oracle": 1521,
        "postgresql": 5432,
    }
    return (
        backend,
        url.host.lower() if url.host else None,
        url.port or default_ports.get(backend),
        url.database,
    )


_test_url = _parse_url(_test_database_url, "TEST_DATABASE_URL")
_development_database_url = os.environ.get("DATABASE_URL")
if _development_database_url is None:
    _development_database_url = dotenv_values(_PROJECT_ROOT / ".env").get(
        "DATABASE_URL"
    )

if _development_database_url:
    _development_url = _parse_url(_development_database_url, "DATABASE_URL")
    if _database_identity(_test_url) == _database_identity(_development_url):
        raise pytest.UsageError(
            "TEST_DATABASE_URL points to the same database as DATABASE_URL; "
            "use a dedicated test database."
        )

# Ensure application settings and any app-created engine use only the test URL.
os.environ["DATABASE_URL"] = _test_database_url


@pytest_asyncio.fixture(scope="function")
async def test_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(_test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(scope="function")
def test_session_factory(
    test_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest_asyncio.fixture(scope="function")
async def test_session(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with test_session_factory() as session:
        yield session
