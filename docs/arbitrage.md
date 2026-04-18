# Arbitraje (Surebets)

## Qué es un arbitraje deportivo

Una **surebet** existe cuando, combinando las mejores cuotas disponibles entre varias casas para cada resultado posible de un mercado, se cumple:

```
Σ (1 / mejor_cuota_i) < 1
```

Si se distribuye el capital proporcionalmente entre cada resultado, la ganancia es **independiente del outcome real** del partido. El beneficio porcentual es:

```
profit_pct = (1 / Σ(1/odds)) − 1
```

Ejemplo (H2H fútbol con 3 outcomes):

| Outcome | Mejor cuota | Bookmaker | 1/odds   |
|---------|-------------|-----------|----------|
| Home    | 2.60        | bet365    | 0.3846   |
| Draw    | 3.80        | pinnacle  | 0.2632   |
| Away    | 4.20        | betfair   | 0.2381   |
|         |             | **Total** | **0.8859** |

→ `profit_pct = (1/0.8859 − 1) = 12.9%` garantizado.

## Pipeline end-to-end

```
OddsAPI ──► fetch_odds_job (cada 15 min) ──► tabla `odds`
                                                  │
                     detect_arbitrage_job ◄───────┘  (cada 15 min)
                              │
                              ├─► ArbitrageDetectionService.detect_all()
                              │       └─► core.arbitrage.detect_arbitrage()
                              │
                              ├─► tabla `arbitrage_opportunities`
                              │
                              └─► TelegramNotifier (para cada AlertConfig activa)
```

## Módulos

### `app/core/arbitrage.py` — lógica pura

Sin dependencias de DB. 100% testeable.

- `find_best_odds(odds_by_bookmaker, outcome_keys)` — selecciona la cuota máxima por outcome.
- `detect_arbitrage(odds_by_bookmaker, outcome_keys, outcome_names, min_profit_pct=0.5, min_bookmakers=5)` — retorna `ArbOpportunity | None`.
- `calculate_stakes(arb, total_capital)` — devuelve stake y payout por pata.

**Dataclasses**:

```python
@dataclass
class ArbLeg:
    outcome_key: str
    outcome_name: str
    bookmaker_key: str
    best_odds: float
    implied_prob: float
    stake_pct: float   # fracción del capital total (0-1)

@dataclass
class ArbOpportunity:
    legs: list[ArbLeg]
    total_implied: float   # Σ(1/best_odds) < 1
    profit_pct: float      # (1/total_implied - 1) * 100
    num_outcomes: int
```

**Cálculo de stake óptimo** (`stake_pct`): proporcional a la probabilidad implícita normalizada, de forma que el payout sea igual en cualquier outcome.

```
stake_pct_i = (1/odds_i) / Σ(1/odds_j)
```

### `app/services/arbitrage_service.py` — orquestación

`ArbitrageDetectionService`:

| Parámetro | Default | Propósito |
|-----------|---------|-----------|
| `min_profit_pct` | `0.5` | filtra surebets menores al 0.5% (ruido) |
| `min_bookmakers` | `5` | exige liquidez mínima |
| `min_minutes_to_kickoff` | `15` | descarta partidos inminentes (cuotas volátiles) |
| `max_minutes_to_kickoff` | `10080` (7 días) | descarta futuros lejanos |
| `max_odds_age_minutes` | `30` | ignora cuotas obsoletas |

**Flujo de `detect_all()`**:

1. Carga `Match.status == "scheduled"` dentro de la ventana temporal.
2. Para cada match → carga sus `Market` activos.
3. Para cada market → obtiene la **última** cuota por `(outcome, bookmaker)` via subquery sobre `Odds`, filtrando por `captured_at >= now - max_odds_age`.
4. Llama a `detect_arbitrage()` con el dict `{bookmaker_key: [odds]}`.
5. Persiste `ArbitrageOpportunity` nuevas o actualiza las existentes (mismo match+market+status `active`).
6. Expira las que ya pasaron de kickoff (`status = "expired"`).

### `app/models/arbitrage.py` — schema

Tabla `arbitrage_opportunities`:

| Columna | Tipo | Notas |
|---------|------|-------|
| `id` | PK | |
| `match_id` | FK → matches (CASCADE) | |
| `market_id` | FK → markets (CASCADE) | |
| `total_implied` | Numeric(8,6) | Σ(1/odds) |
| `profit_pct` | Numeric(6,3) | beneficio % |
| `num_outcomes` | int | 2 o 3 típicamente |
| `legs` | JSON | `[{outcome, outcome_name, bookmaker, odds, stake_pct}]` |
| `status` | String(20) | `active` / `expired` |
| `detected_at` | timestamp | server default now() |
| `expires_at` | timestamp | = `match.commence_time` |
| `closed_at` | timestamp | cuando pasa a expired |

**Índices**: `status`, `profit_pct`, `(match_id, market_id)`.

**Migración**: `alembic/versions/b2c3d4e5f6a7_arbitrage_opportunities.py`.

### `app/workers/jobs.py::detect_arbitrage_job`

Cada 15 minutos:

1. Ejecuta `ArbitrageDetectionService.detect_all()`.
2. Para cada arb nuevo, construye `ArbitragePayload` (home/away/market/profit/legs).
3. Itera sobre `AlertConfig.active == True` y envía via `TelegramNotifier`.

### `app/api/v1/arbitrage.py` — endpoint

```http
GET /api/v1/arbitrage/?status=active&min_profit=0.0
```

**Response**: `list[ArbResponse]` — id, match, commence_time, market_type, profit_pct, total_implied, legs, status, detected_at. Ordenado por `profit_pct DESC`.

> ⚠️ **N+1 conocido**: el handler hace `db.get(Match/Market/MarketType/Team)` en loop. Refactor pendiente a `selectinload`/`joinedload`.

## Notificación Telegram

`ArbitragePayload.format_message()` (en `app/notifications/base.py`) produce un mensaje con emojis que incluye:

- Match + kickoff
- Mercado
- Profit %
- Cada leg: outcome, bookmaker, cuota, % de capital a apostar
- Ejemplo de stakes para un capital de €100

> ⚠️ El valor €100 está **hardcoded**. Parametrizable pendiente.

## Testing

- **Unit** (`tests/unit/test_arbitrage.py`): `find_best_odds`, `detect_arbitrage` (con y sin arb), `calculate_stakes`, casos borde (min_bookmakers, profit mínimo, odds inválidas).
- **Integration** (`tests/integration/test_arbitrage_service.py`): `FakeAdapter` + seed con escenario de 12.9% profit → verifica persistencia y JSON de legs.

## Tuning operativo

- Subir `min_profit_pct` a 1–2% en producción para filtrar surebets que los bookmakers cerrarán rápido.
- Subir `min_bookmakers` a 7–8 en ligas líquidas.
- Acortar `max_odds_age_minutes` a 5–10 en vivo.
- Monitorear `expires_at` vs `detected_at`: ventana media esperada 30–60 min antes de que una casa corrija.
