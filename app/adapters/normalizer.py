"""Normalización de nombres de equipos entre fuentes."""

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team import Team, TeamAlias


class TeamNormalizer:
    FUZZY_THRESHOLD = 85

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
