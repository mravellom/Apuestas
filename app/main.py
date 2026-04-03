import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import router as v1_router
from app.config import settings
from app.middleware import RequestLoggingMiddleware
from app.rate_limit import limiter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup and shutdown events."""
    # Startup
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
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
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(v1_router)

    @application.get("/health")
    async def health_check():
        return {"status": "ok"}

    return application


app = create_app()
