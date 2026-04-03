from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.models.sport import League, Sport
from app.schemas.sport import LeagueResponse, SportResponse

router = APIRouter(prefix="/sports", tags=["sports"])


@router.get("", response_model=list[SportResponse])
async def list_sports(db: DB, _user: CurrentUser):
    result = await db.execute(select(Sport).where(Sport.active.is_(True)).order_by(Sport.name))
    return result.scalars().all()


@router.get("/{sport_key}/leagues", response_model=list[LeagueResponse])
async def list_leagues(sport_key: str, db: DB, _user: CurrentUser):
    result = await db.execute(
        select(League)
        .join(Sport)
        .where(Sport.key == sport_key, League.active.is_(True))
        .order_by(League.name)
    )
    return result.scalars().all()
