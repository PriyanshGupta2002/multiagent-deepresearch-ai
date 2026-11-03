from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.queue import create_redis_pool

from app.modules.auth.router import router as auth_router
from app.modules.research.router import router as research_router


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
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
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
