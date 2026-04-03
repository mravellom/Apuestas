"""Seed data para inicializar la base de datos con datos base."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookmaker import Bookmaker
from app.models.market import MarketType
from app.models.sport import League, Season, Sport

SPORTS = [
    {"key": "football", "name": "Football"},
]

LEAGUES = [
    # España
    {"sport_key": "football", "key": "soccer_spain_la_liga", "name": "La Liga", "country": "Spain"},
    {"sport_key": "football", "key": "soccer_spain_segunda_division", "name": "La Liga 2", "country": "Spain"},
    # Inglaterra
    {"sport_key": "football", "key": "soccer_epl", "name": "Premier League", "country": "England"},
    {"sport_key": "football", "key": "soccer_england_championship", "name": "Championship", "country": "England"},
    # Italia
    {"sport_key": "football", "key": "soccer_italy_serie_a", "name": "Serie A", "country": "Italy"},
    # Alemania
    {"sport_key": "football", "key": "soccer_germany_bundesliga", "name": "Bundesliga", "country": "Germany"},
    # Francia
    {"sport_key": "football", "key": "soccer_france_ligue_one", "name": "Ligue 1", "country": "France"},
    # Portugal
    {"sport_key": "football", "key": "soccer_portugal_primeira_liga", "name": "Primeira Liga", "country": "Portugal"},
    # Países Bajos
    {"sport_key": "football", "key": "soccer_netherlands_eredivisie", "name": "Eredivisie", "country": "Netherlands"},
    # Champions League
    {"sport_key": "football", "key": "soccer_uefa_champs_league", "name": "UEFA Champions League", "country": "Europe"},
    # Europa League
    {"sport_key": "football", "key": "soccer_uefa_europa_league", "name": "UEFA Europa League", "country": "Europe"},
]

MARKET_TYPES = [
    {"key": "h2h", "name": "Match Result (1X2)", "description": "Resultado del partido: local, empate o visitante"},
    {"key": "totals", "name": "Over/Under", "description": "Total de goles por encima o debajo de una línea"},
    {"key": "spreads", "name": "Handicap", "description": "Handicap asiático o europeo"},
    {"key": "draw_no_bet", "name": "Draw No Bet", "description": "Apuesta sin empate, se devuelve si hay empate"},
    {"key": "btts", "name": "Both Teams to Score", "description": "Ambos equipos anotan: sí o no"},
    {"key": "double_chance", "name": "Double Chance", "description": "Doble oportunidad: 1X, X2 o 12"},
]

BOOKMAKERS = [
    # Sharp bookmakers (peso extra en consenso)
    {"key": "pinnacle", "name": "Pinnacle", "is_sharp": True},
    {"key": "betfair_ex_eu", "name": "Betfair Exchange", "is_sharp": True},
    {"key": "matchbook", "name": "Matchbook", "is_sharp": True},
    # Bookmakers regulares
    {"key": "bet365", "name": "Bet365", "is_sharp": False},
    {"key": "williamhill", "name": "William Hill", "is_sharp": False},
    {"key": "unibet_eu", "name": "Unibet", "is_sharp": False},
    {"key": "betsson", "name": "Betsson", "is_sharp": False},
    {"key": "marathonbet", "name": "Marathon Bet", "is_sharp": False},
    {"key": "1xbet", "name": "1xBet", "is_sharp": False},
    {"key": "betway", "name": "Betway", "is_sharp": False},
    {"key": "coolbet", "name": "Coolbet", "is_sharp": False},
    {"key": "sport888", "name": "888sport", "is_sharp": False},
    {"key": "bwin", "name": "Bwin", "is_sharp": False},
    {"key": "betclic", "name": "Betclic", "is_sharp": False},
    {"key": "nordicbet", "name": "NordicBet", "is_sharp": False},
]


async def seed_database(db: AsyncSession) -> dict[str, int]:
    """
    Inserta datos base. Es idempotente: no duplica si ya existen.
    Retorna contadores de lo insertado.
    """
    counts = {"sports": 0, "leagues": 0, "market_types": 0, "bookmakers": 0, "seasons": 0}

    # Sports
    sport_map: dict[str, int] = {}
    for s in SPORTS:
        existing = await db.execute(select(Sport).where(Sport.key == s["key"]))
        sport = existing.scalar_one_or_none()
        if not sport:
            sport = Sport(key=s["key"], name=s["name"])
            db.add(sport)
            await db.flush()
            counts["sports"] += 1
        sport_map[s["key"]] = sport.id

    # Leagues
    for lg in LEAGUES:
        sport_id = sport_map.get(lg["sport_key"])
        if not sport_id:
            continue
        existing = await db.execute(select(League).where(League.key == lg["key"]))
        if not existing.scalar_one_or_none():
            league = League(
                sport_id=sport_id,
                key=lg["key"],
                name=lg["name"],
                country=lg.get("country"),
            )
            db.add(league)
            counts["leagues"] += 1

    await db.flush()

    # Seasons — crear temporada activa para cada liga
    leagues_result = await db.execute(select(League))
    for league in leagues_result.scalars().all():
        existing = await db.execute(
            select(Season).where(Season.league_id == league.id, Season.name == "2025-2026")
        )
        if not existing.scalar_one_or_none():
            season = Season(league_id=league.id, name="2025-2026", active=True)
            db.add(season)
            counts["seasons"] += 1

    # Market Types
    for mt in MARKET_TYPES:
        existing = await db.execute(select(MarketType).where(MarketType.key == mt["key"]))
        if not existing.scalar_one_or_none():
            db.add(MarketType(key=mt["key"], name=mt["name"], description=mt.get("description")))
            counts["market_types"] += 1

    # Bookmakers
    for bk in BOOKMAKERS:
        existing = await db.execute(select(Bookmaker).where(Bookmaker.key == bk["key"]))
        if not existing.scalar_one_or_none():
            db.add(Bookmaker(key=bk["key"], name=bk["name"], is_sharp=bk["is_sharp"]))
            counts["bookmakers"] += 1

    await db.commit()
    return counts
