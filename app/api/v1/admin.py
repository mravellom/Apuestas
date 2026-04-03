from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DB, AdminUser
from app.models.bookmaker import Bookmaker
from app.models.match import Match
from app.models.opportunity import BetTracking, Opportunity
from app.models.sport import League, Sport
from app.models.team import Team
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def system_stats(db: DB, _user: AdminUser):
    """Estadísticas generales del sistema."""
    users = await db.execute(select(func.count(User.id)))
    matches = await db.execute(select(func.count(Match.id)))
    active_opps = await db.execute(
        select(func.count(Opportunity.id)).where(Opportunity.status == "active")
    )
    total_opps = await db.execute(select(func.count(Opportunity.id)))
    teams = await db.execute(select(func.count(Team.id)))
    bets = await db.execute(select(func.count(BetTracking.id)))
    sports = await db.execute(select(func.count(Sport.id)))
    leagues = await db.execute(select(func.count(League.id)))
    bookmakers = await db.execute(select(func.count(Bookmaker.id)))

    return {
        "users": users.scalar(),
        "matches": matches.scalar(),
        "active_opportunities": active_opps.scalar(),
        "total_opportunities": total_opps.scalar(),
        "teams": teams.scalar(),
        "total_bets": bets.scalar(),
        "sports": sports.scalar(),
        "leagues": leagues.scalar(),
        "bookmakers": bookmakers.scalar(),
    }


@router.post("/trigger/fetch")
async def trigger_fetch(db: DB, _user: AdminUser):
    """Trigger manual del job de fetch de cuotas."""
    from app.workers.jobs import fetch_odds_job
    await fetch_odds_job()
    return {"status": "fetch job completed"}


@router.post("/trigger/detect")
async def trigger_detect(db: DB, _user: AdminUser):
    """Trigger manual del job de detección."""
    from app.workers.jobs import detect_value_job
    await detect_value_job()
    return {"status": "detect job completed"}


@router.post("/seed")
async def trigger_seed(db: DB, _user: AdminUser):
    """Trigger manual del seed de datos."""
    from app.services.seed_service import seed_database
    counts = await seed_database(db)
    return {"status": "seed completed", "counts": counts}
