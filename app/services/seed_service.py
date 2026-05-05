"""Seed data para inicializar la base de datos con datos base."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookmaker import Bookmaker
from app.models.broker import Broker
from app.models.market import MarketType
from app.models.sport import League, Season, Sport

SPORTS = [
    {"key": "football", "name": "Football"},
    {"key": "basketball", "name": "Basketball"},
    {"key": "baseball", "name": "Baseball"},
    {"key": "americanfootball", "name": "American Football"},
    {"key": "icehockey", "name": "Ice Hockey"},
    {"key": "mma", "name": "MMA"},
    {"key": "boxing", "name": "Boxing"},
    {"key": "tennis", "name": "Tennis"},
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
    # LATAM
    {"sport_key": "football", "key": "soccer_chile_campeonato", "name": "Primera División Chile", "country": "Chile"},
    {"sport_key": "football", "key": "soccer_brazil_campeonato", "name": "Brasileirão Série A", "country": "Brazil"},
    {"sport_key": "football", "key": "soccer_argentina_primera_division", "name": "Primera División Argentina", "country": "Argentina"},
    {"sport_key": "football", "key": "soccer_italy_serie_b", "name": "Serie B", "country": "Italy"},
    # MLS (US soccer)
    {"sport_key": "football", "key": "soccer_usa_mls", "name": "MLS", "country": "USA"},
    # US sports — MLB activo para detección; NBA/NFL/NHL solo monitoreo
    # (mercados demasiado eficientes para el polling actual; se reevalúan con datos).
    {"sport_key": "baseball", "key": "baseball_mlb", "name": "MLB", "country": "USA"},
    {"sport_key": "basketball", "key": "basketball_nba", "name": "NBA", "country": "USA", "detection_enabled": False},
    {"sport_key": "americanfootball", "key": "americanfootball_nfl", "name": "NFL", "country": "USA", "detection_enabled": False},
    {"sport_key": "icehockey", "key": "icehockey_nhl", "name": "NHL", "country": "USA", "detection_enabled": False},
    # MMA — feed unificado en The Odds API (UFC + Bellator + PFL bajo una sola key).
    # Prototipo: solo H2H 2-way; sharps (Pinnacle vía SportMarket) y US offshore lo cubren.
    {"sport_key": "mma", "key": "mma_mixed_martial_arts", "name": "MMA", "country": "Global"},
    # Boxing — feed unificado en The Odds API. Volumen menor que MMA (carteleras
    # menos frecuentes), pero 2-way h2h puro y Pinnacle suele cotizar.
    {"sport_key": "boxing", "key": "boxing_boxing", "name": "Boxing", "country": "Global"},
    # Tenis — The Odds API tiene una key por torneo, no tour-level. Solo el torneo
    # en curso devuelve eventos; el resto debe togglearse via /admin/leagues/.../toggle
    # cuando rota el calendario. detection_enabled inicial refleja activos al 2026-05-04
    # (semana Roma). Markets: 2-way h2h, Pinnacle siempre cotiza tour principal.
    # ATP
    {"sport_key": "tennis", "key": "tennis_atp_aus_open_singles", "name": "ATP Australian Open", "country": "Australia", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_french_open", "name": "ATP French Open", "country": "France", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_wimbledon", "name": "ATP Wimbledon", "country": "England", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_us_open", "name": "ATP US Open", "country": "USA", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_indian_wells", "name": "ATP Indian Wells", "country": "USA", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_miami_open", "name": "ATP Miami Open", "country": "USA", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_monte_carlo_masters", "name": "ATP Monte Carlo", "country": "Monaco", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_madrid_open", "name": "ATP Madrid Open", "country": "Spain", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_italian_open", "name": "ATP Italian Open", "country": "Italy", "detection_enabled": True},
    {"sport_key": "tennis", "key": "tennis_atp_canadian_open", "name": "ATP Canadian Open", "country": "Canada", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_cincinnati_open", "name": "ATP Cincinnati", "country": "USA", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_shanghai_masters", "name": "ATP Shanghai Masters", "country": "China", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_paris_masters", "name": "ATP Paris Masters", "country": "France", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_barcelona_open", "name": "ATP Barcelona Open", "country": "Spain", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_dubai", "name": "ATP Dubai", "country": "UAE", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_qatar_open", "name": "ATP Qatar Open", "country": "Qatar", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_china_open", "name": "ATP China Open", "country": "China", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_atp_munich", "name": "ATP Munich", "country": "Germany", "detection_enabled": False},
    # WTA
    {"sport_key": "tennis", "key": "tennis_wta_aus_open_singles", "name": "WTA Australian Open", "country": "Australia", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_french_open", "name": "WTA French Open", "country": "France", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_wimbledon", "name": "WTA Wimbledon", "country": "England", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_us_open", "name": "WTA US Open", "country": "USA", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_indian_wells", "name": "WTA Indian Wells", "country": "USA", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_miami_open", "name": "WTA Miami Open", "country": "USA", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_madrid_open", "name": "WTA Madrid Open", "country": "Spain", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_italian_open", "name": "WTA Italian Open", "country": "Italy", "detection_enabled": True},
    {"sport_key": "tennis", "key": "tennis_wta_canadian_open", "name": "WTA Canadian Open", "country": "Canada", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_cincinnati_open", "name": "WTA Cincinnati", "country": "USA", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_dubai", "name": "WTA Dubai", "country": "UAE", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_qatar_open", "name": "WTA Qatar Open", "country": "Qatar", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_china_open", "name": "WTA China Open", "country": "China", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_charleston_open", "name": "WTA Charleston", "country": "USA", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_stuttgart_open", "name": "WTA Stuttgart", "country": "Germany", "detection_enabled": False},
    {"sport_key": "tennis", "key": "tennis_wta_wuhan_open", "name": "WTA Wuhan Open", "country": "China", "detection_enabled": False},
    # Ligas femeninas — opt-in. Se activan manualmente via /admin/leagues/.../toggle
    # cuando se quieran usar como complemento en días flojos de los mercados principales.
    {"sport_key": "basketball", "key": "basketball_wnba", "name": "WNBA", "country": "USA", "detection_enabled": False},
    {"sport_key": "football", "key": "soccer_usa_nwsl", "name": "NWSL", "country": "USA", "detection_enabled": False},
    {"sport_key": "football", "key": "soccer_england_efl_womens", "name": "Women's Super League", "country": "England", "detection_enabled": False},
]

MARKET_TYPES = [
    {"key": "h2h", "name": "Match Result (1X2)", "description": "Resultado del partido: local, empate o visitante"},
    {"key": "totals", "name": "Over/Under", "description": "Total de goles por encima o debajo de una línea"},
    {"key": "spreads", "name": "Handicap", "description": "Handicap asiático o europeo"},
    {"key": "draw_no_bet", "name": "Draw No Bet", "description": "Apuesta sin empate, se devuelve si hay empate"},
    {"key": "btts", "name": "Both Teams to Score", "description": "Ambos equipos anotan: sí o no"},
    {"key": "double_chance", "name": "Double Chance", "description": "Doble oportunidad: 1X, X2 o 12"},
]

BROKERS = [
    # Intermediarios que dan acceso a sharp books a apostadores fuera de sus jurisdicciones.
    # Desde Chile, SportMarket es la puerta de entrada a Pinnacle/Matchbook/SBObet/IBC.
    # Comisión: 1% sobre ganancia (baja a 0.5% con volumen alto).
    {
        "key": "sportmarket",
        "name": "SportMarket",
        "default_commission_pct": Decimal("0.01"),
        "typical_latency_ms": 1000,
    },
]

# Books accesibles vía broker (default commission heredada del broker si no se sobreescribe).
BOOKMAKER_BROKER_MAP = {
    "pinnacle": "sportmarket",
    "matchbook": "sportmarket",
}

BOOKMAKERS = [
    # Sharp bookmakers (peso extra en consenso)
    {"key": "pinnacle", "name": "Pinnacle", "is_sharp": True},
    {"key": "betfair_ex_eu", "name": "Betfair Exchange", "is_sharp": True},
    {"key": "matchbook", "name": "Matchbook", "is_sharp": True},
    # Soft books EU/UK
    {"key": "bet365", "name": "Bet365", "is_sharp": False},
    {"key": "williamhill", "name": "William Hill", "is_sharp": False},
    {"key": "unibet_eu", "name": "Unibet", "is_sharp": False},
    {"key": "betsson", "name": "Betsson", "is_sharp": False},
    {"key": "marathonbet", "name": "Marathon Bet", "is_sharp": False},
    {"key": "onexbet", "name": "1xBet", "is_sharp": False},
    {"key": "betway", "name": "Betway", "is_sharp": False},
    {"key": "coolbet", "name": "Coolbet", "is_sharp": False},
    {"key": "sport888", "name": "888sport", "is_sharp": False},
    {"key": "bwin", "name": "Bwin", "is_sharp": False},
    {"key": "betclic", "name": "Betclic", "is_sharp": False},
    {"key": "nordicbet", "name": "NordicBet", "is_sharp": False},
    # US offshore (accesibles desde Chile, cubren US sports)
    {"key": "bovada", "name": "Bovada", "is_sharp": False},
    {"key": "betonlineag", "name": "BetOnline", "is_sharp": False},
    {"key": "mybookieag", "name": "MyBookie", "is_sharp": False},
    {"key": "betus", "name": "BetUS", "is_sharp": False},
    {"key": "lowvig", "name": "LowVig.ag", "is_sharp": True},  # baja vig = cuotas más sharp
]


async def seed_database(db: AsyncSession) -> dict[str, int]:
    """
    Inserta datos base. Es idempotente: no duplica si ya existen.
    Retorna contadores de lo insertado.
    """
    counts = {"sports": 0, "leagues": 0, "market_types": 0, "bookmakers": 0, "seasons": 0, "brokers": 0}

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

    # Leagues. `detection_enabled` solo se aplica en inserciones; en ligas
    # existentes respeta el toggle manual del usuario (via admin endpoint) —
    # correr el seed varias veces no debe revertir decisiones operativas.
    for lg in LEAGUES:
        sport_id = sport_map.get(lg["sport_key"])
        if not sport_id:
            continue
        detection_enabled = lg.get("detection_enabled", True)
        existing = await db.execute(select(League).where(League.key == lg["key"]))
        league = existing.scalar_one_or_none()
        if not league:
            db.add(League(
                sport_id=sport_id,
                key=lg["key"],
                name=lg["name"],
                country=lg.get("country"),
                detection_enabled=detection_enabled,
            ))
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

    # Brokers — crear antes de bookmakers porque bookmaker.broker_id los referencia
    broker_map: dict[str, int] = {}
    for br in BROKERS:
        existing = await db.execute(select(Broker).where(Broker.key == br["key"]))
        broker = existing.scalar_one_or_none()
        if not broker:
            broker = Broker(
                key=br["key"],
                name=br["name"],
                default_commission_pct=br["default_commission_pct"],
                typical_latency_ms=br["typical_latency_ms"],
            )
            db.add(broker)
            await db.flush()
            counts["brokers"] += 1
        broker_map[br["key"]] = broker.id

    # Bookmakers
    for bk in BOOKMAKERS:
        broker_key = BOOKMAKER_BROKER_MAP.get(bk["key"])
        broker_id = broker_map.get(broker_key) if broker_key else None

        existing = await db.execute(select(Bookmaker).where(Bookmaker.key == bk["key"]))
        bookmaker = existing.scalar_one_or_none()
        if not bookmaker:
            db.add(Bookmaker(
                key=bk["key"],
                name=bk["name"],
                is_sharp=bk["is_sharp"],
                broker_id=broker_id,
            ))
            counts["bookmakers"] += 1
        elif bookmaker.broker_id != broker_id:
            # Re-linking if broker assignment changed
            bookmaker.broker_id = broker_id

    await db.commit()
    return counts
