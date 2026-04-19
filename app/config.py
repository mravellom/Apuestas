from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://valuebet:valuebet@localhost:5432/valuebet"

    # JWT
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # The Odds API
    ODDS_API_KEY: str = ""
    ODDS_API_BASE_URL: str = "https://api.the-odds-api.com/v4"
    # Comma-separated bookmaker keys. Empty = accept all. Non-empty = allowlist applied at ingest.
    BOOKMAKERS_ALLOWED: str = ""
    # Value detection reference model. Empty = consensus (needs >=3 books).
    # Set to a bookmaker key (e.g. "pinnacle") to treat that book as "true odds".
    VALUE_REFERENCE_BOOKMAKER: str = ""
    # Minimum bookmakers for arbitrage scan. Drop to 2 when using restricted allowlist.
    ARB_MIN_BOOKMAKERS: int = 5
    # Mínimo profit_pct (net, post-comisión). Valores más altos = menos ruido pero menos arbs.
    ARB_MIN_PROFIT_PCT: float = 0.5
    # Edad máxima de una cuota para considerarla fresca en detección de arbs.
    # Con fetch cada 15min, 20 es más seguro que 30 (evita cuotas stale).
    ARB_MAX_ODDS_AGE_MINUTES: int = 20
    # Ventana temporal hacia el futuro para escanear partidos. 72h evita arbs de
    # líneas "palp error" muy anticipadas que típicamente no son reales.
    ARB_MAX_HOURS_TO_KICKOFF: int = 72
    # Minimum EV for value detection (0.01 = 1%). Lower with sharp reference; higher with consensus.
    VALUE_MIN_EV: float = 0.03
    # Scheduler intervals (seconds). Defaults are quota-safe for The Odds API free tier.
    # Drop to 30-60s only with paid plans — polling costs one request per league per interval.
    SCHEDULER_FETCH_ODDS_SECONDS: int = 15 * 60
    SCHEDULER_DETECT_SECONDS: int = 15 * 60
    SCHEDULER_SCORES_SECONDS: int = 30 * 60

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""

    # SMTP (Email)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # App
    APP_ENV: str = "development"
    DEBUG: bool = True

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
