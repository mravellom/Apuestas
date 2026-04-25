# Estrategia operativa — ValueBet Engine

**Documento vivo** — última revisión: 2026-04-24
**Operador**: Chile, bankroll inicial ~$20,000 USD
**Modo activo**: arbitraje (value betting OFF por ROI empírico negativo −32%)

---

## 1. Contexto y restricciones de partida

### Restricciones geográficas (Chile)

- NO accesible directo desde Chile: Pinnacle, SBObet, IBC, Matchbook, Betfair Exchange
- Acceso a sharp books **únicamente vía broker intermediario**: SportMarket (principal) + Stake.com (crypto, complementario)
- Comisión SportMarket: ~1% sobre ganancia (0.5% con volumen alto)
- Latencia broker: ~1s vs 5s direct vs 10s+ exchange manual

### Ligas NO ejecutables (deshabilitadas en `leagues.detection_enabled`)

EPL, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie, Portugal Primeira, Champions League, Europa League — sus mercados están dominados por libros UK/EU que no aceptan registros desde Chile.

### Capacidad operativa

- Bankroll: $20k USD distribuibles en SportMarket + Stake + soft books LATAM/US
- Horario peak: 19:00–02:00 CLT (US sports + Brasileirão/Argentina noche)
- Quiet window 04:00–12:00 UTC (00–08 CLT) ya configurada

---

## 2. Métricas operativas de partida

| Métrica | Valor |
|---|---|
| Paper bets arbitraje settleados | 24 |
| ROI paper arbitraje all-time | **+1.086%** |
| Paper bets value (descontinuado) | 145 con ROI **−32.06%** |
| Arbs detectados últimos 7 días | 27 (~4/día) |
| Closing lines acumuladas | 4,402 |
| Ligas activas (post-cleanup 04-24) | MLB, NBA, MLS, Argentina Primera |

---

## 3. Las tres opciones estratégicas evaluadas

### Opción A — Agresivo

**Tesis**: maximizar ingreso del año 1 explotando soft books al máximo antes de que limiten cuentas.

**Configuración**:
- `ARB_MIN_PROFIT_PCT` = 0.8% (umbral bajo)
- `SCHEDULER_FETCH_ODDS_SECONDS` = 300 (5 min)
- The Odds API plan **Enthusiast $119/mes** obligatorio
- 4-5 soft books activos en paralelo
- Stakes $2.5–3.5k por leg
- Activar todas las ligas latam-friendly
- 6-10 horas/día atención (turno noche full-time)

**Proyección año 1**: $50–80k bruto / $25–50k neto
**Proyección año 2-3 sostenido**: $50–95k/año
**Probabilidad burnout 12 meses**: 40-60%
**Probabilidad outcome negativo año 1**: 15-25%

---

### Opción B — Conservador

**Tesis**: proteger optionality, construir track record sólido, transicionar a value betting con modelo propio en año 2.

**Configuración**:
- Mantener `ARB_MIN_PROFIT_PCT` = 1.2%
- Mantener fetch 15 min, plan Starter $30
- Sólo 1-2 soft books, priorizando Pinnacle vía SportMarket
- Stakes $500–1.5k por leg
- 1-2 horas/día atención
- Compatible con día job

**Proyección año 1**: $15–30k
**Proyección año 2-3 con modelo propio**: $40–70k/año
**Probabilidad burnout**: muy baja
**Probabilidad outcome negativo**: <3%

---

### Opción C — Híbrido balanceado ✅ ELEGIDA

**Tesis**: capturar 70-80% del upside del agresivo con 30% de su intensidad y fracción de su riesgo. Sostenibilidad multi-año desde día 1.

**Configuración**:
- `ARB_MIN_PROFIT_PCT` = 1.0% (intermedio)
- `SCHEDULER_FETCH_ODDS_SECONDS` = 600 (10 min)
- Plan API Starter $30 inicialmente, upgrade a Enthusiast $119 sólo si ROI lo justifica
- 2-3 soft books rotando (no quemar uno hasta morir)
- Stakes $1.5–2.5k por leg
- 2-3 horas/día atención (compatible con día job o vida normal)
- Disciplina mug bets desde día 1 (20-30% apuestas recreacionales para diluir patrón)

**Proyección año 1**: $30–45k bruto / $20–35k neto
**Proyección año 2-3 sostenido**: $50–80k/año (con modelo propio en año 2)
**Probabilidad burnout**: media-baja
**Probabilidad outcome negativo año 1**: <5%

---

## 4. Comparación lado a lado

| Dimensión | A (agresivo) | B (conservador) | **C (híbrido)** |
|---|---|---|---|
| Horas/día | 6-10 | 1-2 | **2-3** |
| Ingreso año 1 (bruto) | $50-80k | $15-30k | **$30-45k** |
| Ingreso neto año 1 | $25-50k | $12-25k | **$20-35k** |
| Ingreso sostenido año 2-3 | $50-95k | $40-70k | **$50-80k** |
| Desviación estándar resultado | ±$25k | ±$8k | **±$12k** |
| Prob. outcome negativo año 1 | 15-25% | <3% | **<5%** |
| Prob. burnout 12 meses | 40-60% | <5% | **10-15%** |
| Prob. sostenibilidad año 3+ | 40-50% | 80% | **70%** |
| Compatible con trabajo día | NO | Sí | **Sí** |
| Velocidad acumulación dataset cierre | Rápida | Lenta | **Media** |

---

## 5. Por qué se eligió la Opción C

### Razón #1 — La curva ingreso/intensidad es decreciente

A no duplica el ingreso de C. Apenas lo multiplica por ~1.5x. Pero **multiplica la intensidad por ~3-4x** y el riesgo por ~3x. La relación esfuerzo/retorno marginal de A es notoriamente peor.

### Razón #2 — Sin experiencia previa, A es temerario

Al 2026-04-24 hay solo 24 paper bets de arbitraje settleados. Estadísticamente eso es **muestra cero**. No hay base empírica para apostar full-time. La probabilidad de descubrir un edge case del motor o del mercado bajo presión real es alta. C deja margen para aprender sin colapsar.

### Razón #3 — Los ingresos sostenidos año 2+ convergen entre A y C

El pilar de largo plazo es el mismo en ambas: Pinnacle vía SportMarket + dataset propio para modelo de value betting. A te gana plata extra solo el año 1; en años 2-3 los ingresos son comparables porque ambos chocan contra el techo de soft book limits.

### Razón #4 — C protege optionality

Si en mes 4 las cosas no salen como esperado (ROI cae, drawdown, problema personal), bajar intensidad desde C es trivial. Bajar desde A implica perder ingresos que ya estabas dependiendo financieramente. C no obliga a comprometer salario fijo ni capital de emergencia.

### Razón #5 — Año 1 con C deja tiempo para construir el activo real

El **dataset de closing lines** es el verdadero moat sostenible (no los arbs individuales). Con C dedicas energía mental a:
- Capturar closing lines correctamente (4,402 acumuladas)
- Validar el motor estadísticamente (gate: 50+ settleados con ROI >0.8%)
- Iterar settings con disciplina experimental
- Investigar bugs y latencia de ejecución

A te obliga a dedicar el 80% de la energía a clicks de ejecución. C deja 40-50% para el trabajo de fondo.

### Razón #6 — Compromiso del operador "todo lo necesario" interpretado correctamente

La intención fue maximizar éxito sostenido, no hacer turno noche por hacer turno noche. C honra esa intención: la disciplina y consistencia 5 noches a la semana 2-3h vencen al sprint heroico que termina en burnout.

---

## 6. Plan de ejecución por fases

### Fase 0 — Diagnóstico (semana del 2026-04-24) ✅ EN CURSO

- [x] Verificar paper trading state (24 settleados, ROI +1.086%)
- [x] Confirmar capture_closing_lines funcionando
- [x] Identificar ligas productivas: NBA (1.55% avg) y MLB (0.96% avg)
- [x] Desactivar ligas sin retorno: NHL y Brasileirão (0 arbs en 20 días)
- [x] Activar ligas Tier 1: MLS y Argentina Primera División
- [x] Refactor `fetch_scores_job` derivar ligas desde DB (en vez de hardcoded list)
- [x] Migrar a perfil dev Docker con volume mount + reload

### Fase 1 — Setup paralelo (semanas 1-4, hasta ~2026-05-22)

- [ ] **SportMarket KYC**: cédula chilena, comprobante domicilio. Lead time 2-4 semanas.
- [ ] **Stake.com**: abrir cuenta crypto. 1 día.
- [ ] **Consulta tributaria**: contador chileno con experiencia operaciones offshore. $80–150 USD una hora.
- [ ] **Mantener settings actuales sin tocar** hasta 50+ settleados.
- [ ] **Checkin 2026-04-30**: re-correr queries validation plan.
- [ ] Activar `basketball_wnba` cuando arranque temporada (2026-05-14).

### Fase 2 — Aplicar settings C (mes 2, post-validación)

Solo si Fase 0/1 confirma ROI paper >0.8% sobre 50+ settleados:

- [ ] `ARB_MIN_PROFIT_PCT`: 1.2 → **1.0**
- [ ] `SCHEDULER_FETCH_ODDS_SECONDS`: 900 → **600**
- [ ] Evaluar upgrade API Starter $30 → Enthusiast $119
- [ ] **Primera apuesta REAL** con stake mínimo $300-500/leg para calibrar flujo
- [ ] Definir disciplina mug bets (20-30% apuestas)

### Fase 3 — Ramp a régimen (meses 3-5)

- [ ] Stakes a $1.5-2.5k/leg gradualmente
- [ ] 2-3 soft books rotando + Pinnacle siempre
- [ ] Target $2-3.5k/mes
- [ ] Disciplina anti-limit: stakes no-redondos, mug bets, timing variado, mezcla mercados

### Fase 4 — Sostenido + dataset (mes 6+)

- [ ] Procesar dataset closing lines acumulado
- [ ] Evaluar prototipo modelo propio para value betting
- [ ] Mantener disciplina psicológica: NO escalar a A "porque está funcionando"
- [ ] Transición gradual a Pinnacle/Matchbook como columna principal (60%+ del volumen)

---

## 7. Settings de operación

### Actuales (.env, post-cleanup 2026-04-24)

```
ARB_MIN_PROFIT_PCT=1.2          # umbral elevado tras intento fallido 04-23
ARB_MIN_BOOKMAKERS=2            # bajo porque allowlist es restringida
ARB_MAX_ODDS_AGE_MINUTES=15     # estricto contra cuotas stale
SCHEDULER_FETCH_ODDS_SECONDS=900   # 15 min
SCHEDULER_DETECT_SECONDS=300       # 5 min
SCHEDULER_SCORES_SECONDS=3600      # 1h
VALUE_DETECTION_ENABLED=false     # OFF por ROI -32%
VALUE_REFERENCE_BOOKMAKER=pinnacle
BOOKMAKERS_ALLOWED=pinnacle,coolbet,betsson,onexbet,bovada,betonlineag,mybookieag,betus,lowvig
FETCH_ODDS_QUIET_START_UTC=4
FETCH_ODDS_QUIET_END_UTC=12
```

### Objetivo Fase 2 (aplicar al pasar el gate)

```
ARB_MIN_PROFIT_PCT=1.0          # bajar para capturar más arbs ejecutables
SCHEDULER_FETCH_ODDS_SECONDS=600   # 10 min, más frecuencia
# resto sin cambios
```

### Ligas activas

| Sport | Liga | Estado | Promedio profit | Notas |
|---|---|---|---|---|
| baseball | baseball_mlb | ✅ | 0.96% | Mucho volumen, threshold marginal |
| basketball | basketball_nba | ✅ | 1.55% (max 2.50%) | Mejor liga, prioridad |
| football | soccer_usa_mls | ✅ (recién activada) | TBD | Books US offshore + Pinnacle |
| football | soccer_argentina_primera_division | ✅ (recién activada) | TBD | Coolbet/Betsson/Pinnacle |
| basketball | basketball_wnba | ⏳ activar 2026-05-14 | — | Histórico fuente arbs |
| icehockey | icehockey_nhl | ❌ desactivada 04-24 | 0 arbs en 20 días | Reevaluar otra ventana |
| football | soccer_brazil_campeonato | ❌ desactivada 04-24 | 0 arbs en 20 días | Reevaluar otra ventana |

---

## 8. Mapa de riesgos operativos

| Riesgo | Probabilidad | Impacto típico | Mitigación |
|---|---|---|---|
| Partial fill (una pierna sí, otra se mueve) | Alta (5-10% arbs) | -$100-500 | Ejecutar pierna soft primero, Pinnacle segundo |
| Book void bet ganada (palpable error) | Media (2-5%/mes) | Pérdida stake del leg | Evitar cuotas extremas (>5.0 o <1.3) |
| Limit soft book | Certeza | Pérdida 20-40% capacidad | Mug bets, stakes no-redondos, timing variado |
| Account closure + fondos retenidos | Baja (1-3%/año/libro) | -$500-3000 | Diversificar, retiros mensuales |
| Broker quiebra/retiene fondos | Muy baja, catastrófica | -$5-10k | Nunca >25-30% bankroll en un broker |
| Bug detección (falso arb) | Media | 1-3% stake | Code review, test de fórmulas, monitor profit_pct extremos |
| Variance estadística | Certeza | Drawdown 10-20% | Disciplina staking, no chase |
| Chile SII fiscalización | Baja año 1, creciente | 35% sobre ganancias + intereses | Consulta tributaria, declarar correctamente |
| Banco CLP cuestiona transferencias | Media | 1-4 semanas sin acceso | Documentación lista, multi-banco |
| Currency risk USD/CLP | Certeza | ±5-15% anual | Mantener en USD, retiros parciales |
| **Psicológico (tilt/chase/burnout)** | **Alta sin disciplina** | **Variable, causa #1 fracaso** | **Stakes calculados, no override, descansos** |

---

## 9. Pilares sostenibles año 2+ (sin techo por limits)

1. **Pinnacle vía SportMarket** — no limita, capacidad infinita, columna vertebral
2. **Matchbook / Betfair Exchange vía SportMarket** — apuestas P2P, ilimitado por diseño
3. **Dataset propio de closing lines** — 4,402 acumuladas, target 50,000+ para entrenar modelo de value betting año 2

---

## 10. Decisiones recurrentes (no acumular memoria, releer este doc)

- Si el ROI paper baja consistentemente debajo de 0.5% → reevaluar threshold y ligas activas
- Si llega a 200+ settleados con ROI estable >1% → considerar pasar a Fase 4 antes de tiempo
- Si una liga produce 0 arbs por 30 días → desactivar
- Si un soft book limita la cuenta → no abrir nuevo inmediatamente; rotar a otro existente
- Si aparece partial fill rate >15% sostenido → revisar latencia y orden de ejecución
- Si SportMarket modifica términos (comisión, retiros, KYC) → reevaluar bankroll allocation

---

## 11. Métricas a monitorear semanalmente

```sql
-- Settleados acumulados + ROI paper arbitraje
SELECT COUNT(*) AS settleados, ROUND(AVG(profit_pct)::numeric, 3) AS roi_pct
FROM paper_bets
WHERE source_type='arbitrage' AND result IN ('won','lost','void');

-- Arbs por liga última semana
SELECT l.key, COUNT(*) AS arbs, ROUND(AVG(a.profit_pct)::numeric, 2) AS avg_profit
FROM arbitrage_opportunities a
JOIN matches m ON m.id=a.match_id
JOIN seasons se ON se.id=m.season_id
JOIN leagues l ON l.id=se.league_id
WHERE a.detected_at >= NOW() - INTERVAL '7 days'
GROUP BY l.key ORDER BY arbs DESC;

-- Closing lines últimas 24h (debe ser >0 todos los días con games)
SELECT COUNT(*), MAX(captured_at) FROM closing_lines
WHERE captured_at >= NOW() - INTERVAL '24 hours';

-- Salud DB y scheduler (revisar si hay match scheduled con commence_time pasado >2h)
SELECT COUNT(*) FROM matches WHERE status='scheduled' AND commence_time < NOW() - INTERVAL '2 hours';
```

---

## 12. Próximos checkpoints

| Fecha | Acción |
|---|---|
| **2026-04-30** | Re-evaluar muestra (target 50+ settleados), decidir Fase 2 |
| **2026-05-14** | Activar WNBA (inicio temporada) |
| **2026-05-22** | Confirmar SportMarket operativo, primer depósito |
| **2026-06-01** | Primera apuesta real (post-validación) |
| **2026-08-01** | Revisión trimestral: ¿en track con proyección $2-3.5k/mes? |
| **2026-12-01** | Cierre año 1: total neto, salud cuentas, plan año 2 |
