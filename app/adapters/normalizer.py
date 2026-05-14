"""Normalización de nombres de equipos entre fuentes."""

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team import Team, TeamAlias


class TeamNormalizer:
    FUZZY_THRESHOLD = 85
    # Threshold para `same_team` (matching de outcome name → home/away).
    # Más bajo que FUZZY_THRESHOLD porque outcome names suelen ser variantes
    # cortas ("Red Sox" vs "Boston Red Sox") y token_set_ratio devuelve 100
    # cuando uno es subset del otro — el threshold solo importa para distinguir
    # entre dos equipos del mismo match.
    SAME_TEAM_THRESHOLD = 80

    @staticmethod
    def match_score(a: str, b: str) -> int:
        """Score 0-100 de similitud textual entre dos nombres de equipo.

        100 si coinciden exacto (case/whitespace-insensitive). Si no,
        token_set_ratio para tolerar abreviaciones (`"Red Sox"` ≈ `"Boston
        Red Sox"`). Comparación pura, sin DB.
        """
        if not a or not b:
            return 0
        if a.strip().lower() == b.strip().lower():
            return 100
        return int(fuzz.token_set_ratio(a.lower(), b.lower()))

    @classmethod
    def resolve_side(
        cls,
        outcome_name: str,
        home_team_name: str | None,
        away_team_name: str | None,
    ) -> str | None:
        """Devuelve `'home'`/`'away'` si `outcome_name` matchea con uno de los
        dos equipos por encima del threshold; `None` si ninguno o si hay
        empate (ambiguo). Usado por `_normalize_outcome_key` para canonizar
        outcomes de spreads/h2h sin fracturar el mercado por variantes del
        nombre (`"Red Sox"` vs `"Boston Red Sox"`).

        Cuando ambos lados pasan el threshold (caso típico: equipos con un
        token en común como `"Detail A"` vs `"Detail H"`), se elige el de
        score más alto. Si empatan exactamente, se devuelve `None` para
        que el caller use fallback — preferimos un outcome verboso a uno
        mal mapeado.
        """
        home_score = cls.match_score(outcome_name, home_team_name or "")
        away_score = cls.match_score(outcome_name, away_team_name or "")
        if max(home_score, away_score) < cls.SAME_TEAM_THRESHOLD:
            return None
        if home_score > away_score:
            return "home"
        if away_score > home_score:
            return "away"
        return None  # tie — ambiguous

    async def resolve(
        self, raw_name: str, source: str, sport_id: int, db: AsyncSession
    ) -> int | None:
        """
        Resuelve un nombre crudo a un team_id canónico.

        1. Busca coincidencia exacta en team_aliases
        2. Si no, fuzzy matching contra canonical_names
        3. Si fuzzy >= threshold, crea alias automáticamente
        4. Si < threshold, retorna None (pendiente de revisión manual)
        """
        # 1. Exact match in aliases
        result = await db.execute(
            select(TeamAlias.team_id).where(
                TeamAlias.alias == raw_name, TeamAlias.source == source
            )
        )
        team_id = result.scalar_one_or_none()
        if team_id is not None:
            return team_id

        # 2. Fuzzy match against canonical names
        result = await db.execute(
            select(Team).where(Team.sport_id == sport_id)
        )
        teams = result.scalars().all()
        if not teams:
            return None

        names = {t.canonical_name: t.id for t in teams}
        match = process.extractOne(raw_name, names.keys(), scorer=fuzz.ratio)

        if match and match[1] >= self.FUZZY_THRESHOLD:
            matched_name = match[0]
            matched_team_id = names[matched_name]

            # 3. Auto-create alias
            alias = TeamAlias(team_id=matched_team_id, alias=raw_name, source=source)
            db.add(alias)
            await db.flush()
            return matched_team_id

        # 4. No match found
        return None

    async def get_or_create_team(
        self, raw_name: str, source: str, sport_id: int, db: AsyncSession
    ) -> int:
        """Resuelve o crea un equipo nuevo si no existe."""
        team_id = await self.resolve(raw_name, source, sport_id, db)
        if team_id is not None:
            return team_id

        # Create new team with raw_name as canonical
        team = Team(sport_id=sport_id, canonical_name=raw_name)
        db.add(team)
        await db.flush()

        # Create alias for this source
        alias = TeamAlias(team_id=team.id, alias=raw_name, source=source)
        db.add(alias)
        await db.flush()

        return team.id
