from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import Date, cast, func, select

from app.api.deps import DB, CurrentUser
from app.core.formulas import calculate_roi
from app.models.arbitrage import ArbitrageOpportunity
from app.models.opportunity import BetTracking
from app.models.user import Bankroll
from app.schemas.user import PerformanceSummary

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("/summary", response_model=PerformanceSummary)
async def get_summary(db: DB, user: CurrentUser):
    result = await db.execute(
        select(BetTracking).where(BetTracking.user_id == user.id)
    )
    bets = result.scalars().all()

    total_bets = len(bets)
    won = sum(1 for b in bets if b.result == "won")
    lost = sum(1 for b in bets if b.result == "lost")
    pending = sum(1 for b in bets if b.result is None)
    total_staked = float(sum(b.stake_amount for b in bets))
    total_profit = float(sum(b.profit_loss or 0 for b in bets))
    win_rate = (won / (won + lost) * 100) if (won + lost) > 0 else 0.0
    roi = calculate_roi(total_profit, total_staked)

    return PerformanceSummary(
        total_bets=total_bets,
        won=won,
        lost=lost,
        pending=pending,
        win_rate=round(win_rate, 2),
        total_staked=round(total_staked, 2),
        total_profit=round(total_profit, 2),
        roi=round(roi, 2),
    )


# ── Daily deployment metric (Opción A) ────────────────────────────────────────
# "Banca desplegable por día": cuánto capital real se desplegó cada día contra
# el tamaño de banca actual del usuario. Mide utilización efectiva. La fuente
# de verdad es bet_tracking (apuestas reales). paper_bets queda fuera.


class DailyDeploymentRow(BaseModel):
    date: date  # día calendario en CLT (America/Santiago)
    num_bets: int
    num_arbs: int  # arbs distintos tocados ese día (excluye value bets sueltas)
    total_stake: float
    settled_stake: float
    realized_profit: float
    settled_bets: int
    pending_bets: int
    theoretical_edge_avg_pct: float | None  # promedio de profit_pct de los arbs del día
    realized_roi_pct: float | None  # 100 * realized_profit / settled_stake
    utilization_pct: float | None  # 100 * total_stake / bankroll_total


class DailyDeploymentSummary(BaseModel):
    bankroll_total: float
    bankroll_currency: str | None
    avg_utilization_pct: float
    avg_theoretical_edge_pct: float | None
    realized_roi_pct: float | None
    total_stake_period: float
    total_realized_profit: float
    days_with_activity: int


class DailyDeploymentResponse(BaseModel):
    window_days: int
    generated_at: str
    summary: DailyDeploymentSummary
    rows: list[DailyDeploymentRow]


SETTLED_RESULTS = ("won", "lost", "void")


@router.get("/daily-deployment", response_model=DailyDeploymentResponse)
async def get_daily_deployment(
    db: DB,
    user: CurrentUser,
    days: int = Query(30, ge=1, le=365),
):
    """Capital desplegado en bet_tracking por día (CLT) vs banca actual."""
    placed_or_created = func.coalesce(BetTracking.placed_at, BetTracking.created_at)
    # Las timestamps son naive UTC; las pasamos a CLT antes de truncar al día.
    day_clt = cast(
        func.timezone("America/Santiago", func.timezone("UTC", placed_or_created)),
        Date,
    ).label("day")

    # Ventana en UTC: tomamos N días en CLT y traducimos el inicio a UTC para
    # filtrar el WHERE eficientemente con índice sobre placed_at/created_at.
    today_utc = datetime.now(timezone.utc)
    # Las columnas en DB son `timestamp without time zone` (naive UTC), así que
    # el filtro debe ser naive también para que asyncpg no rechace el bind.
    window_start = (today_utc - timedelta(days=days)).replace(tzinfo=None)

    # Agregado principal por día
    settled_filter = BetTracking.result.in_(SETTLED_RESULTS)
    pending_filter = BetTracking.result.is_(None)

    rows_stmt = (
        select(
            day_clt,
            func.count(BetTracking.id).label("num_bets"),
            func.count(func.distinct(BetTracking.arbitrage_id)).label("num_arbs"),
            func.coalesce(func.sum(BetTracking.stake_amount), 0).label("total_stake"),
            func.coalesce(
                func.sum(BetTracking.stake_amount).filter(settled_filter), 0
            ).label("settled_stake"),
            func.coalesce(
                func.sum(BetTracking.profit_loss).filter(settled_filter), 0
            ).label("realized_profit"),
            func.count(BetTracking.id).filter(settled_filter).label("settled_bets"),
            func.count(BetTracking.id).filter(pending_filter).label("pending_bets"),
        )
        .where(BetTracking.user_id == user.id)
        .where(placed_or_created >= window_start)
        .group_by(day_clt)
    )
    rows_result = await db.execute(rows_stmt)
    rows_by_day: dict[date, dict] = {
        r.day: {
            "num_bets": int(r.num_bets),
            "num_arbs": int(r.num_arbs),
            "total_stake": float(r.total_stake),
            "settled_stake": float(r.settled_stake),
            "realized_profit": float(r.realized_profit),
            "settled_bets": int(r.settled_bets),
            "pending_bets": int(r.pending_bets),
        }
        for r in rows_result
    }

    # Edge teórico: promedio del profit_pct de arbs distintos por día.
    # Hacemos DISTINCT (day, arbitrage_id, profit_pct) y promediamos en Python
    # para evitar contar el mismo arb dos veces por sus dos legs.
    edge_stmt = (
        select(
            day_clt,
            BetTracking.arbitrage_id,
            ArbitrageOpportunity.profit_pct,
        )
        .join(ArbitrageOpportunity, ArbitrageOpportunity.id == BetTracking.arbitrage_id)
        .where(BetTracking.user_id == user.id)
        .where(placed_or_created >= window_start)
        .where(BetTracking.arbitrage_id.is_not(None))
        .distinct()
    )
    edge_result = await db.execute(edge_stmt)
    edges_by_day: dict[date, list[float]] = {}
    for r in edge_result:
        edges_by_day.setdefault(r.day, []).append(float(r.profit_pct))

    # Banca total del usuario (suma de current_amount de todos sus bankrolls).
    # Si tiene varios en distintas monedas, devolvemos la suma cruda y la
    # primera moneda — el frontend ya muestra el caveat.
    br_total_stmt = select(
        func.coalesce(func.sum(Bankroll.current_amount), 0),
        func.min(Bankroll.currency),
    ).where(Bankroll.user_id == user.id)
    br_row = (await db.execute(br_total_stmt)).one()
    bankroll_total = float(br_row[0])
    bankroll_currency = br_row[1]

    # Construimos una fila por cada día del periodo (incluye días sin actividad).
    today_clt = _today_clt()
    out_rows: list[DailyDeploymentRow] = []
    for offset in range(days):
        d = today_clt - timedelta(days=offset)
        agg = rows_by_day.get(d)
        edges = edges_by_day.get(d, [])
        edge_avg = sum(edges) / len(edges) if edges else None

        if agg is None:
            out_rows.append(
                DailyDeploymentRow(
                    date=d,
                    num_bets=0,
                    num_arbs=0,
                    total_stake=0.0,
                    settled_stake=0.0,
                    realized_profit=0.0,
                    settled_bets=0,
                    pending_bets=0,
                    theoretical_edge_avg_pct=edge_avg,
                    realized_roi_pct=None,
                    utilization_pct=0.0 if bankroll_total > 0 else None,
                )
            )
            continue

        realized_roi = (
            100.0 * agg["realized_profit"] / agg["settled_stake"]
            if agg["settled_stake"] > 0
            else None
        )
        utilization = (
            100.0 * agg["total_stake"] / bankroll_total
            if bankroll_total > 0
            else None
        )
        out_rows.append(
            DailyDeploymentRow(
                date=d,
                **agg,
                theoretical_edge_avg_pct=edge_avg,
                realized_roi_pct=realized_roi,
                utilization_pct=utilization,
            )
        )

    # Resumen agregado del periodo
    days_with_activity = sum(1 for r in out_rows if r.num_bets > 0)
    util_values = [r.utilization_pct for r in out_rows if r.utilization_pct is not None]
    avg_utilization = sum(util_values) / len(util_values) if util_values else 0.0
    edge_values = [
        r.theoretical_edge_avg_pct for r in out_rows if r.theoretical_edge_avg_pct is not None
    ]
    avg_edge = sum(edge_values) / len(edge_values) if edge_values else None
    total_stake_period = sum(r.total_stake for r in out_rows)
    total_realized = sum(r.realized_profit for r in out_rows)
    total_settled_stake = sum(r.settled_stake for r in out_rows)
    realized_roi_period = (
        100.0 * total_realized / total_settled_stake if total_settled_stake > 0 else None
    )

    summary = DailyDeploymentSummary(
        bankroll_total=round(bankroll_total, 2),
        bankroll_currency=bankroll_currency,
        avg_utilization_pct=round(avg_utilization, 3),
        avg_theoretical_edge_pct=round(avg_edge, 3) if avg_edge is not None else None,
        realized_roi_pct=round(realized_roi_period, 3) if realized_roi_period is not None else None,
        total_stake_period=round(total_stake_period, 2),
        total_realized_profit=round(total_realized, 2),
        days_with_activity=days_with_activity,
    )

    return DailyDeploymentResponse(
        window_days=days,
        generated_at=today_utc.isoformat(),
        summary=summary,
        rows=out_rows,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────
try:
    from zoneinfo import ZoneInfo  # py>=3.9

    _CLT_TZ = ZoneInfo("America/Santiago")
except Exception:  # pragma: no cover
    _CLT_TZ = timezone.utc


def _today_clt() -> date:
    return datetime.now(_CLT_TZ).date()
