#!/usr/bin/env bash
# Diagnóstico post-overnight: confirma qué encontró el motor mientras dormías.
# Uso: bash scripts/check_overnight.sh

set -e
DB="docker exec valuebet-db-1 psql -U valuebet -d valuebet"

echo "════════════════════════════════════════════════════════"
echo "  1. Arbs detectados en las últimas 12h"
echo "════════════════════════════════════════════════════════"
$DB -c "
SELECT
  a.id,
  to_char(a.detected_at, 'MM-DD HH24:MI') AS detected,
  a.profit_pct,
  l.key AS league,
  th.canonical_name || ' vs ' || tw.canonical_name AS match,
  to_char(m.commence_time, 'MM-DD HH24:MI') AS kickoff,
  a.status
FROM arbitrage_opportunities a
JOIN matches m ON m.id = a.match_id
JOIN teams th ON th.id = m.home_team_id
JOIN teams tw ON tw.id = m.away_team_id
JOIN seasons s ON s.id = m.season_id
JOIN leagues l ON l.id = s.league_id
WHERE a.detected_at > NOW() - INTERVAL '12 hours'
ORDER BY a.detected_at DESC;
"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  2. Fetches exitosos en las últimas 12h"
echo "════════════════════════════════════════════════════════"
echo "(contando batches de odds capturados; cada fetch inserta ~500-800 odds)"
$DB -c "
SELECT
  date_trunc('minute', captured_at) AS fetch_minute,
  COUNT(*) AS odds_count
FROM odds
WHERE captured_at > NOW() - INTERVAL '12 hours'
GROUP BY date_trunc('minute', captured_at)
ORDER BY fetch_minute DESC
LIMIT 15;
"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  3. Cuota API consumida (aprox)"
echo "════════════════════════════════════════════════════════"
$DB -c "
SELECT
  COUNT(DISTINCT date_trunc('minute', captured_at)) * 1 AS approximate_api_calls,
  MIN(captured_at) AS first_fetch,
  MAX(captured_at) AS last_fetch
FROM odds
WHERE captured_at > NOW() - INTERVAL '12 hours';
"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  4. Errores del scheduler (si hay)"
echo "════════════════════════════════════════════════════════"
docker logs valuebet-api-1 --since 12h 2>&1 | grep -iE "error|failed|exception" | grep -v "401\|credentials" | tail -20 || echo "  (ninguno)"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  5. Ingest coverage (qué books llegaron)"
echo "════════════════════════════════════════════════════════"
docker logs valuebet-api-1 --since 12h 2>&1 | grep "ingest.coverage" | tail -10 || echo "  (sin logs de coverage)"
