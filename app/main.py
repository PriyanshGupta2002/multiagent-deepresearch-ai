from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    app_exception_handler,
    http_exception_handler,
    unexpected_exception_handler,
    validation_exception_handler,
)
from app.modules.conversations.models import (
    ResearchConversation,
    ResearchMessage,
)
from app.core.queue import create_redis_pool

from app.modules.auth.router import router as auth_router
from app.modules.research.router import router as research_router
from app.modules.saved_reports.router import router as saved_reports_router
from app.modules.conversations.router import router as conversations_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis_pool = await create_redis_pool()

    try:
        yield
    finally:
        await app.state.redis_pool.aclose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    exception_handlers={
        AppException: app_exception_handler,
        RequestValidationError: validation_exception_handler,
        StarletteHTTPException: http_exception_handler,
        Exception: unexpected_exception_handler,
    },
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Last-Event-ID"],
)


@app.get("/")
async def read_root():
    return {
        "message": "Welcome to DeepResearch AI",
        "status": "running",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


app.include_router(
    auth_router,
    prefix=settings.API_V1_PREFIX,
)

app.include_router(
    research_router,
    prefix=settings.API_V1_PREFIX,
)

app.include_router(
    saved_reports_router,
    prefix=settings.API_V1_PREFIX,
)

app.include_router(conversations_router, prefix=settings.API_V1_PREFIX)
