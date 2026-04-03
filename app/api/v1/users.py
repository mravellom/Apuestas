from decimal import Decimal

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.models.user import Bankroll, UserConfig
from app.schemas.user import (
    BankrollCreate,
    BankrollResponse,
    BankrollUpdate,
    UserConfigResponse,
    UserConfigUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/config", response_model=UserConfigResponse)
async def get_config(db: DB, user: CurrentUser):
    result = await db.execute(select(UserConfig).where(UserConfig.user_id == user.id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    return config


@router.put("/config", response_model=UserConfigResponse)
async def update_config(data: UserConfigUpdate, db: DB, user: CurrentUser):
    result = await db.execute(select(UserConfig).where(UserConfig.user_id == user.id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)

    await db.flush()
    return config


@router.get("/bankroll", response_model=list[BankrollResponse])
async def list_bankrolls(db: DB, user: CurrentUser):
    result = await db.execute(select(Bankroll).where(Bankroll.user_id == user.id))
    return result.scalars().all()


@router.post("/bankroll", response_model=BankrollResponse, status_code=201)
async def create_bankroll(data: BankrollCreate, db: DB, user: CurrentUser):
    bankroll = Bankroll(
        user_id=user.id,
        name=data.name,
        currency=data.currency,
        initial_amount=Decimal(str(data.initial_amount)),
        current_amount=Decimal(str(data.initial_amount)),
    )
    db.add(bankroll)
    await db.flush()
    return bankroll


@router.put("/bankroll/{bankroll_id}", response_model=BankrollResponse)
async def update_bankroll(bankroll_id: int, data: BankrollUpdate, db: DB, user: CurrentUser):
    bankroll = await db.get(Bankroll, bankroll_id)
    if not bankroll or bankroll.user_id != user.id:
        raise HTTPException(status_code=404, detail="Bankroll not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "current_amount" and value is not None:
            value = Decimal(str(value))
        setattr(bankroll, field, value)

    await db.flush()
    return bankroll
