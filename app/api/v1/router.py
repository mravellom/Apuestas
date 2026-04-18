from fastapi import APIRouter

from app.api.v1 import admin, alerts, arbitrage, auth, matches, opportunities, paper, performance, sports, users

router = APIRouter(prefix="/api/v1")

router.include_router(arbitrage.router)
router.include_router(auth.router)
router.include_router(sports.router)
router.include_router(matches.router)
router.include_router(opportunities.router)
router.include_router(paper.router)
router.include_router(users.router)
router.include_router(performance.router)
router.include_router(alerts.router)
router.include_router(admin.router)
