import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import router as v1_router
from app.config import settings
from app.logging_config import configure_logging
from app.middleware import RequestLoggingMiddleware
from app.rate_limit import limiter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup and shutdown events."""
    # Startup
    configure_logging(
        level=settings.resolved_log_level,
        fmt=settings.resolved_log_format,
    )

    # Run seed on startup
    try:
        from app.database import async_session
        from app.services.seed_service import seed_database

        async with async_session() as db:
            counts = await seed_database(db)
            if any(v > 0 for v in counts.values()):
                logger.info("Seed completed: %s", counts)
    except Exception as e:
        logger.warning("Seed skipped (DB may not be ready): %s", e)

    # Start scheduler
    try:
        from app.workers.scheduler import start_scheduler
        start_scheduler()
        logger.info("Scheduler started")
    except Exception as e:
        logger.warning("Scheduler failed to start: %s", e)

    yield

    # Shutdown
    try:
        from app.workers.scheduler import shutdown_scheduler
        shutdown_scheduler()
    except Exception:
        pass


def create_app() -> FastAPI:
    application = FastAPI(
        title="ValueBet Engine",
        description="Motor de detección de value bets deportivas",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    application.add_middleware(RequestLoggingMiddleware)
    # CORS: con allow_credentials=True la spec prohíbe allow_origins=["*"].
    # Enumeramos orígenes explícitos del frontend dev + prod.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://192.168.1.84:3000",  # red local (mobile testing)
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(v1_router)

    # Expone /metrics con latencias HTTP por endpoint (p50/p95/p99, counts).
    # Las métricas de jobs del scheduler las emite app/metrics.py vía track_job.
    Instrumentator().instrument(application).expose(
        application, endpoint="/metrics", include_in_schema=False
    )

    @application.get("/health")
    async def health_check():
        return {"status": "ok"}

    return application


app = create_app()
