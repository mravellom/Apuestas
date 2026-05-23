from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://valuebet:valuebet@localhost:5432/valuebet"

    # JWT
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS: orígenes EXTRA aceptados, separados por coma. Los defaults
    # (localhost:3000 + 127.0.0.1:3000) siempre están permitidos. Útil para
    # IPs de red local de testing en mobile o el dominio prod del frontend.
    # Ejemplo: "http://192.168.1.84:3000,https://valuebet.example.com"
    CORS_EXTRA_ORIGINS: str = ""

    # --- Retención de datos (cleanup_job los purga por edad) ---
    # `odds`: tabla más grande (cuotas snapshotted cada 5-15min). Con scoring
    # ya hecho y arbs persistidos, los registros viejos solo sirven para
    # auditoría — 30 días alcanza. A 0 desactiva la purga.
    RETENTION_ODDS_DAYS: int = 30
    # `closing_lines`: snapshot pre-kickoff, base del CLV tracking. Más valor
    # histórico (validar edge en el tiempo), retención larga.
    RETENTION_CLOSING_LINES_DAYS: int = 365
    # `api_usage_log`: monitoreo de quota de The Odds API. 90d cubre revisiones
    # de capacidad sin acumular indefinidamente.
    RETENTION_API_USAGE_DAYS: int = 90

    # The Odds API
    ODDS_API_KEY: str = ""
    ODDS_API_BASE_URL: str = "https://api.the-odds-api.com/v4"
    # Threshold para alertar bajo consumo de quota. Cuando requests_remaining
    # cae bajo este valor, fetch_odds_job loguea warning y dispara admin alert
    # una sola vez por umbral cruzado. En 0 el job omite el fetch (sin
    # créditos = no tiene sentido pegar al endpoint).
    ODDS_API_LOW_QUOTA_THRESHOLD: int = 200
    # Comma-separated bookmaker keys. Empty = accept all. Non-empty = allowlist applied at ingest.
    BOOKMAKERS_ALLOWED: str = ""
    # Value detection reference model. Empty = consensus (needs >=3 books).
    # Set to a bookmaker key (e.g. "pinnacle") to treat that book as "true odds".
    VALUE_REFERENCE_BOOKMAKER: str = ""
    # Minimum bookmakers for arbitrage scan. Drop to 2 when using restricted allowlist.
    ARB_MIN_BOOKMAKERS: int = 5
    # Mínimo profit_pct (net, post-comisión). Valores más altos = menos ruido pero menos arbs.
    ARB_MIN_PROFIT_PCT: float = 0.5
    # Threshold específico para arbs sobre líneas alternate (no-centrales) de
    # totals/spreads. Se exige más profit porque las colas de la distribución
    # de líneas (over 5.5 / over 13.5 cuando consenso es 8.5) concentran palp
    # errors: cuotas absurdas que el libro corrige en segundos. Empieza en 1.5%.
    ARB_MIN_PROFIT_PCT_ALT: float = 1.5
    # Ingesta de mercados alternate_totals/alternate_spreads desde The Odds API.
    # Off por default: cada (sport, alt_market) habilitado cuesta +1 request
    # por fetch a la quota. Encender por sport gradualmente vía SPORT_ALT_MARKETS
    # en jobs.py tras observar yield real de arbs vs falsos positivos.
    FETCH_ALT_MARKETS: bool = False
    # Edad máxima de una cuota para considerarla fresca en detección de arbs.
    # Con fetch cada 15min, 20 es más seguro que 30 (evita cuotas stale).
    ARB_MAX_ODDS_AGE_MINUTES: int = 20
    # Ventana temporal hacia el futuro para escanear partidos. 72h evita arbs de
    # líneas "palp error" muy anticipadas que típicamente no son reales.
    ARB_MAX_HOURS_TO_KICKOFF: int = 72
    # Minimum EV for value detection (0.01 = 1%). Lower with sharp reference; higher with consensus.
    VALUE_MIN_EV: float = 0.03
    # Interruptor general de la detección de value bets. En false, el scheduler
    # no registra el job `detect_value` — las oportunidades existentes y su
    # histórico permanecen en DB pero no se generan nuevas.
    VALUE_DETECTION_ENABLED: bool = True
    # Scheduler intervals (seconds). Defaults are quota-safe for The Odds API free tier.
    # Drop to 30-60s only with paid plans — polling costs one request per league per interval.
    # Para fetch_odds este valor es el TICK del scheduler; la cadencia efectiva
    # se modula adentro del job según proximidad del próximo partido.
    SCHEDULER_FETCH_ODDS_SECONDS: int = 5 * 60
    SCHEDULER_DETECT_SECONDS: int = 15 * 60
    # Detección de arbitraje en cadencia separada (más agresiva). Los arbs de
    # ≥5% profit_pct viven ~30min en promedio (la mayoría son palp errors
    # corregidos rápido por el libro); con detect a 15min se pierde el 47%
    # de su vida útil antes de mostrarlos al usuario. No toca la API externa
    # — solo CPU local sobre las cuotas ya ingestadas.
    SCHEDULER_DETECT_ARBITRAGE_SECONDS: int = 5 * 60
    SCHEDULER_SCORES_SECONDS: int = 30 * 60
    # Franja horaria UTC en la que fetch_odds se salta la llamada externa para
    # ahorrar créditos. `start` inclusivo, `end` exclusivo, con wraparound si
    # start > end (ej. 22..6 = 22:00-05:59 UTC). Ambos iguales = sin skip.
    # Default 4..12 UTC cubre 00:00-07:59 CLT (UTC-4), franja donde no hay
    # fútbol europeo ni MLB activo y la data histórica muestra cero arbs.
    FETCH_ODDS_QUIET_START_UTC: int = 4
    FETCH_ODDS_QUIET_END_UTC: int = 12
    # Smart polling: cadencia dinámica de fetch_odds según horas hasta el
    # próximo partido con detección activa. Histórico 14d muestra que el 70%
    # de arbs jugosos (avg ≥3% profit) aparecen en la ventana 1-3h pre-kickoff,
    # así que fetcheamos más densamente ahí y back-off cuando no hay partidos.
    FETCH_ODDS_NEAR_KICKOFF_HOURS: int = 3
    FETCH_ODDS_MID_KICKOFF_HOURS: int = 12
    FETCH_ODDS_INTERVAL_NEAR_SECONDS: int = 5 * 60
    FETCH_ODDS_INTERVAL_MID_SECONDS: int = 15 * 60
    FETCH_ODDS_INTERVAL_FAR_SECONDS: int = 30 * 60

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    # Chat al que se envían alertas de infraestructura (jobs falando,
    # API key inválida, etc.). Vacío = alertas admin silenciadas.
    ADMIN_TELEGRAM_CHAT_ID: str = ""

    # Salud de jobs: tras N fallos consecutivos del mismo job, se dispara
    # una alerta admin. La alerta se manda UNA vez por incidente — si
    # sigue fallando, no spamea.
    JOB_FAILURE_ALERT_THRESHOLD: int = 3

    # SMTP (Email)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # App
    APP_ENV: str = "development"
    DEBUG: bool = True
    # Formato de logs: 'text' (legible en dev) o 'json' (parsing por log
    # shippers en prod). Vacío = auto: 'text' si APP_ENV=='development'
    # else 'json'.
    LOG_FORMAT: str = ""
    LOG_LEVEL: str = ""

    @property
    def resolved_log_format(self) -> str:
        if self.LOG_FORMAT:
            return self.LOG_FORMAT
        return "text" if self.APP_ENV == "development" else "json"

    @property
    def resolved_log_level(self) -> str:
        if self.LOG_LEVEL:
            return self.LOG_LEVEL
        return "DEBUG" if self.DEBUG else "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
