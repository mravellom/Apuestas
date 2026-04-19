-- Cleanup de bookmakers fantasma creados antes del fix de bug #4.
--
-- Estos fueron auto-creados por _get_or_create_bookmaker con commission_pct=0
-- cuando The Odds API devolvió books no seedeados. Algunos son exchanges
-- (smarkets, betfair_ex_uk) que SÍ cobran comisión real, así que tratarlos
-- con 0% inflaba el profit_pct de arbs históricos.
--
-- Los marcamos inactive para que:
--   - Los detectores los ignoren (arbitrage_service + opportunity_service
--     filtran por Bookmaker.active.is_(True) tras el fix de bug #4).
--   - No se borre data histórica (los Odds ingeridos con estos books
--     quedan en DB para trazabilidad, solo no entran al pipeline).
--
-- Para reactivar alguno en el futuro:
--   UPDATE bookmakers
--     SET active = true, commission_pct = 0.02, is_sharp = true
--     WHERE key = 'smarkets';

UPDATE bookmakers
SET active = false
WHERE key IN (
  '1xbet',            -- rename antiguo de onexbet (duplicado)
  'pmu_fr',
  'winamax_fr',
  'winamax_de',
  'codere_it',
  'paddypower',
  'skybet',
  'smarkets',         -- exchange, cobra 2% — deshabilitar hasta seedear correcto
  'unibet_fr',
  'betfair_ex_uk',    -- exchange, cobra 2-5% — ídem
  'tipico_de',
  'betclic_fr',
  'betvictor',
  'boylesports',
  'leovegas',
  'unibet_se',
  'leovegas_se',
  'grosvenor',
  'livescorebet',
  'virginbet',
  'unibet_nl',
  'casumo',
  'betfair_sb_uk',
  'gtbets',
  'everygame',
  'ladbrokes_uk',
  'coral',
  'betfred_uk',
  'unibet_uk'
);
