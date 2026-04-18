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
    # Minimum EV for value detection (0.01 = 1%). Lower with sharp reference; higher with consensus.
    VALUE_MIN_EV: float = 0.03

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
