# Closing Lines & Odds History

## Qué es el Closing Line Value (CLV)

La **closing line** es la última cuota publicada por una casa antes del kickoff. Se considera la mejor estimación pública de la probabilidad real del evento, porque integra toda la información de mercado (movimientos de dinero, lesiones, alineaciones, etc.).

El **CLV** mide si apostaste a una cuota mejor que el cierre:

```
CLV = (cuota_apostada / cuota_cierre) − 1
```

Consistentemente batir el closing line (CLV > 0 en promedio) es el indicador más fuerte de edge a largo plazo — más robusto que el ROI a corto plazo, que está dominado por varianza.

## Diseño

### Tabla `closing_lines`

Definida en `app/models/market.py:57`. Migración: `alembic/versions/a1b2c3d4e5f6_odds_history_and_closing_lines.py`.

| Columna | Tipo | Notas |
|---------|------|-------|
| `id` | PK | |
| `outcome_id` | FK → outcomes (CASCADE) | |
| `bookmaker_id` | FK → bookmakers | |
| `price` | Numeric(8,4) | cuota decimal |
| `captured_at` | timestamp | cuándo se tomó la cuota (del row `odds`) |
| `created_at` | timestamp | cuándo se insertó el closing line |

**Constraints**:
- `UNIQUE(outcome_id, bookmaker_id)` con nombre `uq_closing_outcome_bm` — cada par outcome+bookmaker tiene **un solo** closing line.
- `INDEX(outcome_id)` — `idx_closing_outcome`.

### Índices adicionales sobre `odds`

La misma migración añade índices sobre la tabla de histórico de cuotas para acelerar consultas de “última cuota por outcome+bookmaker”:

- `idx_odds_outcome_bookmaker` sobre `(outcome_id, bookmaker_id)`
- `idx_odds_captured` sobre `captured_at`

Estos soportan el subquery `MAX(captured_at) GROUP BY outcome_id, bookmaker_id` usado por `ArbitrageDetectionService._get_latest_odds_by_bookmaker` y por el propio job de closing lines.

## Captura: `capture_closing_lines_job`

Definido en `app/workers/jobs.py:151`. Registrado en el scheduler cada **1 minuto** (`app/workers/scheduler.py:57`).

**Flujo**:

1. Calcula ventana: partidos con `commence_time ∈ (now, now + 5 min]` y `status = "scheduled"`.
2. Para cada match, carga todos los `Outcome` (a través del join con `Market`).
3. Para cada outcome, consulta la **última** cuota por bookmaker:
   ```sql
   SELECT DISTINCT ON (bookmaker_id) bookmaker_id, price, captured_at
   FROM odds
   WHERE outcome_id = :o_id
   ORDER BY bookmaker_id, captured_at DESC
   ```
4. Inserta en `closing_lines` con `INSERT ... ON CONFLICT DO NOTHING` sobre el constraint `uq_closing_outcome_bm`.

**Idempotencia**: ejecutar el job varias veces en la ventana de 5 min es seguro — el `ON CONFLICT DO NOTHING` garantiza que **sólo la primera captura** se conserva. El timestamp `captured_at` refleja cuándo fue publicada la cuota original por la casa, no cuándo se insertó en `closing_lines`.

**Por qué 1 min / ventana 5 min**: maximiza la probabilidad de capturar la última cuota disponible justo antes del kickoff, aun si el job se salta una ejecución. La primera ejecución que encuentre el match en la ventana inserta; las siguientes son no-op.

## Usos previstos

### 1. Medición de CLV por usuario

Comparar cada bet del usuario con la closing line:

```python
clv = user_bet.odds / closing_line.price - 1
```

Agregados útiles:
- CLV medio por estrategia (Kelly vs flat).
- % de bets con CLV > 0 ("beat rate").
- Distribución por bookmaker (algunos bookies mueven más lento → más CLV disponible).

### 2. Backtesting del detector

Para validar que el `OpportunityDetectionService` encuentra **valor real**:
- Tomar todas las `Opportunity` detectadas en T-60 min.
- Calcular la probabilidad implícita del closing line (devigged con Shin).
- Comparar con la probabilidad de consenso usada al detectar.
- Una estrategia con edge real debería tener value esperado > 0 medido contra el cierre.

### 3. Calibración del modelo Shin

Shin (`app/core/formulas.py:25`) depende del overround observado. Con histórico de `odds` + cierre se puede verificar que las probabilidades devigged predicen mejor los outcomes que el método proporcional.

## Endpoints (pendientes)

Actualmente **no hay endpoints expuestos** para closing lines. Próximos pasos razonables:

- `GET /api/v1/performance/clv` — resumen CLV del usuario.
- `GET /api/v1/matches/{id}/closing-lines` — snapshot de cierre por outcome.
- `GET /api/v1/backtesting/opportunities` — performance histórica del detector.

## Notas operativas

- **Partidos sin cierre capturado**: si el scheduler está caído durante los 5 min previos, ningún closing line se graba. Considerar un job de recuperación que use la última cuota disponible pre-kickoff desde `odds`.
- **Bookmakers offline**: si una casa no publicó cuotas recientes, su `closing_line` no existirá — filtrar `NULL` en los joins.
- **Retención**: la tabla `odds` crece rápido (~1 row por outcome × bookmaker × fetch). Closing lines es compacta (una fila final por outcome+bookmaker). Política de purga para `odds` > 30 días es recomendable; `closing_lines` debe conservarse indefinidamente para backtesting.
