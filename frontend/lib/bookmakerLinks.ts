/**
 * URLs públicas por bookmaker para deep-linking en la pantalla de ejecución
 * asistida. Pensado para minimizar fricción manual al ejecutar arbs desde
 * Chile.
 *
 * **Regla**: los books accedidos vía broker (commission_pct > 0 en nuestra
 * config actual) apuntan al portal del broker — desde Chile el acceso
 * directo a Pinnacle/Matchbook/SBObet/IBC está geo-bloqueado y la ruta
 * operativa real es SportMarket Pro. Si en el futuro se suma AsianConnect
 * o se cambia de broker, expandir esta lógica (mapear por broker.key).
 *
 * Lista no exhaustiva — books no mapeados muestran el nombre sin botón
 * "abrir" (no rompen el flujo). Agregar URLs conforme se confirme que el
 * usuario puede operar en cada uno desde Chile.
 */

const SPORTMARKET_URL = "https://www.sportmarket.com/login";

export const BOOKMAKER_URLS: Record<string, string> = {
  // Sharp books vía SportMarket (broker, comisión 1%)
  pinnacle: SPORTMARKET_URL,
  matchbook: SPORTMARKET_URL,
  sbobet: SPORTMARKET_URL,
  ibcbet: SPORTMARKET_URL,

  // US offshore (acceso directo desde Chile típicamente sin VPN)
  betonlineag: "https://www.betonline.ag/sportsbook",
  mybookieag: "https://www.mybookie.ag/sportsbook/",
  betus: "https://www.betus.com.pa/sportsbook",
  bovada: "https://www.bovada.lv/sports",
  lowvig: "https://www.lowvig.ag/sportsbook",
  gtbets: "https://www.gtbets.eu/sportsbook",
  everygame: "https://www.everygame.eu/sportsbook",

  // EU / Nordic
  coolbet: "https://www.coolbet.com/en/sports",
  betsson: "https://www.betsson.com/es/apuestas-deportivas",
  onexbet: "https://1xbet.com/line",
};

/**
 * Devuelve la URL pública del bookmaker, o `null` si no está mapeado.
 */
export function bookmakerUrl(bookmakerKey: string): string | null {
  return BOOKMAKER_URLS[bookmakerKey] ?? null;
}

/**
 * Heurística: en la config actual (un solo broker = SportMarket), comisión > 0
 * en la pierna implica book vía broker → disparar al final. Direct access
 * (comisión 0) → disparar primero porque puede vanish/limitar.
 */
export function isBrokerAccessed(commissionPct: number): boolean {
  return commissionPct > 0;
}

/**
 * Label corto para mostrar en el botón de "abrir". Para books vía broker
 * usamos "SportMarket" porque ahí es donde el usuario realmente apuesta.
 */
export function openLinkLabel(
  bookmakerName: string,
  commissionPct: number,
): string {
  return isBrokerAccessed(commissionPct) ? "SportMarket" : bookmakerName;
}
