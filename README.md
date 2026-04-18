# ValueBet Engine

Motor de detección de **value bets** y **arbitraje deportivo** para fútbol. Ingesta cuotas desde múltiples bookmakers, calcula probabilidad justa (consenso con corrección Shin del vig) y alerta oportunidades vía Telegram/Email/Webhook.

## Características

- **Value bets**: detecta cuotas con valor esperado positivo contra consenso de mercado.
- **Arbitraje (surebets)**: encuentra combinaciones de cuotas con ganancia garantizada (`Σ 1/odds < 1`).
- **Closing lines**: congela la última cuota pre-kickoff para medir CLV (Closing Line Value).
- **Staking**: Kelly fraccionado (1/4 por defecto) o flat betting.
- **Auth JWT** con roles `free` / `premium` / `admin`.
- **Scheduler** asíncrono (APScheduler) con jobs de fetch, detección y captura.
- **Notificaciones** multicanal: Telegram, Email, Webhook.

## Stack

- **Lenguaje**: Python 3.12
- **API**: FastAPI + Uvicorn
- **DB**: PostgreSQL 16 + SQLAlchemy 2.0 async + asyncpg
- **Migraciones**: Alembic
- **Scheduler**: APScheduler
- **Fuentes**: The Odds API + scraper Oddschecker

## Estructura

```
app/
├── adapters/         Integraciones externas (Odds API, scrapers)
├── api/v1/           Routers FastAPI
├── core/             Lógica pura (formulas, arbitrage, value_detector, staking)
├── models/           ORM SQLAlchemy
├── services/         Orquestación (ingesta, detección, notificaciones)
├── notifications/    Canales (Telegram, Email, Webhook)
├── workers/          Jobs periódicos y scheduler
├── schemas/          Pydantic
└── main.py           App factory + lifespan
alembic/versions/     Migraciones de DB
tests/                unit/ + integration/ + api/
scripts/              Utilidades (seed_alert.py)
docs/                 Documentación técnica
```

## Setup

### 1. Clonar y configurar entorno

```bash
git clone <repo> && cd ValueBet
cp .env.example .env   # edita valores (ODDS_API_KEY, SECRET_KEY, etc.)
```

### 2. Opción A — Docker Compose

```bash
docker compose up -d         # producción
docker compose --profile dev up api-dev  # desarrollo con reload
```

API en `http://localhost:8000`, DB en `localhost:5435`.

### 2. Opción B — Local

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Levanta sólo la DB:
docker compose up -d db

alembic upgrade head
uvicorn app.main:app --reload
```

## Variables de entorno

Ver `.env.example`. Las clave son:

| Variable | Descripción |
|----------|-------------|
| `DATABASE_URL` | URL async de Postgres (`postgresql+asyncpg://...`) |
| `SECRET_KEY` | Clave JWT — **cámbiala en producción** |
| `ODDS_API_KEY` | API key de [the-odds-api.com](https://the-odds-api.com) |
| `TELEGRAM_BOT_TOKEN` | Token del bot para notificaciones |
| `SMTP_*` | Config SMTP para notificaciones por email |
| `DEBUG` | `true` en desarrollo |

## Uso

- **Docs interactivas**: `http://localhost:8000/docs` (Swagger) o `/redoc`
- **Health check**: `GET /health`
- **Endpoints principales** (prefix `/api/v1`):
  - `POST /auth/register`, `POST /auth/login`
  - `GET /opportunities/` — value bets detectadas
  - `GET /arbitrage/` — surebets detectadas
  - `GET /matches/`, `GET /sports/`
  - `POST /alerts/` — configurar alertas Telegram
  - `GET /performance/` — ROI / CLV del usuario

## Jobs periódicos

Configurados en `app/workers/scheduler.py`:

| Job | Frecuencia | Qué hace |
|-----|-----------|----------|
| `fetch_odds` | 15 min | Descarga cuotas de The Odds API |
| `detect_value` | 15 min | Detecta value bets y notifica |
| `detect_arbitrage` | 15 min | Detecta surebets y notifica |
| `capture_closing_lines` | 1 min | Congela cuotas finales (<5 min kickoff) |
| `cleanup` | 1 h | Marca partidos pasados como completados |

## Tests

```bash
pytest                              # suite completa
pytest --cov=app --cov-report=term  # con cobertura
pytest tests/unit/                  # sólo unitarios
pytest tests/integration/           # sólo integración
```

Estado actual: **137 tests pasan** • cobertura total **70%** • `core/` y `models/` >94%.

## Migraciones

```bash
alembic upgrade head                 # aplicar todas
alembic downgrade -1                 # revertir última
alembic revision --autogenerate -m "nombre"   # crear nueva
```

Migraciones existentes:
- `2bde049fbac1` — esquema inicial
- `a1b2c3d4e5f6` — índices de odds + tabla `closing_lines`
- `b2c3d4e5f6a7` — tabla `arbitrage_opportunities`

## Documentación técnica

- [`docs/arbitrage.md`](docs/arbitrage.md) — detector de surebets
- [`docs/closing-lines.md`](docs/closing-lines.md) — captura CLV y backtesting

## Licencia

Privada — uso interno.
