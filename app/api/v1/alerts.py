import logging
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DB, PremiumUser
from app.models.alert import AlertConfig
from app.notifications.service import build_test_payload, get_notifier
from app.schemas.alert import AlertConfigCreate, AlertConfigResponse, AlertConfigUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertTestResponse(BaseModel):
    """Resultado de un envío de prueba al canal configurado."""
    ok: bool
    error: str | None = None


@router.get("/config", response_model=list[AlertConfigResponse])
async def list_alerts(db: DB, user: PremiumUser):
    result = await db.execute(select(AlertConfig).where(AlertConfig.user_id == user.id))
    return result.scalars().all()


@router.post("/config", response_model=AlertConfigResponse, status_code=201)
async def create_alert(data: AlertConfigCreate, db: DB, user: PremiumUser):
    # Max 10 alerts per user
    count_result = await db.execute(
        select(AlertConfig).where(AlertConfig.user_id == user.id)
    )
    if len(count_result.scalars().all()) >= 10:
        raise HTTPException(status_code=400, detail="Maximum 10 alert configurations allowed")

    alert = AlertConfig(
        user_id=user.id,
        channel=data.channel,
        destination=data.destination,
        min_value_pct=Decimal(str(data.min_value_pct)),
        sports_filter=data.sports_filter,
        leagues_filter=data.leagues_filter,
    )
    db.add(alert)
    await db.flush()
    return alert


@router.put("/config/{alert_id}", response_model=AlertConfigResponse)
async def update_alert(alert_id: int, data: AlertConfigUpdate, db: DB, user: PremiumUser):
    alert = await db.get(AlertConfig, alert_id)
    if not alert or alert.user_id != user.id:
        raise HTTPException(status_code=404, detail="Alert config not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "min_value_pct" and value is not None:
            value = Decimal(str(value))
        setattr(alert, field, value)

    await db.flush()
    return alert


@router.delete("/config/{alert_id}", status_code=204)
async def delete_alert(alert_id: int, db: DB, user: PremiumUser):
    alert = await db.get(AlertConfig, alert_id)
    if not alert or alert.user_id != user.id:
        raise HTTPException(status_code=404, detail="Alert config not found")

    await db.delete(alert)


@router.post("/config/{alert_id}/test", response_model=AlertTestResponse)
async def test_alert(alert_id: int, db: DB, user: PremiumUser):
    """
    Dispara un envío de prueba al canal configurado en este alert. Útil para
    validar credenciales (token Telegram, SMTP, URL webhook) sin esperar a
    que aparezca una oportunidad real.

    No persiste nada — el resultado se devuelve inline. Errores del canal
    (timeout, auth) se devuelven como `{ok: false, error: "..."}` para que
    la UI los muestre, no como 5xx.
    """
    alert = await db.get(AlertConfig, alert_id)
    if not alert or alert.user_id != user.id:
        raise HTTPException(status_code=404, detail="Alert config not found")

    payload = build_test_payload()
    try:
        notifier = get_notifier(alert.channel)
    except ValueError as e:
        # Canal corrupto en DB — muy poco probable porque create_alert no lo
        # permite, pero defensivo.
        return AlertTestResponse(ok=False, error=str(e))

    try:
        success = await notifier.send(alert.destination, payload)
    except Exception as e:
        logger.warning("Test alert %d failed: %s", alert_id, e)
        return AlertTestResponse(ok=False, error=f"{type(e).__name__}: {e}")

    if not success:
        return AlertTestResponse(
            ok=False,
            error="El canal aceptó la llamada pero reportó fallo. Revisa logs del servidor para detalle.",
        )
    return AlertTestResponse(ok=True)
