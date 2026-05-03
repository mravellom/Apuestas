// Colores de marca por deporte/liga. Prioriza `league` (más específico); si no
// hay match cae al color del sport. Se usan hex directos en inline styles para
// no depender del safelist de Tailwind.
//
// Criterio de los colores:
//   - baseball (MLB)         → rojo (MLB logo)
//   - basketball (NBA)       → naranja (balón)
//   - icehockey (NHL)        → cyan (hielo)
//   - americanfootball (NFL) → amarillo oscuro (field)
//   - football por liga:
//       EPL                  → morado
//       La Liga              → dorado
//       Serie A              → azul (Italia)
//       Bundesliga           → rojo oscuro
//       Ligue 1              → azul claro
//       Champions/Europa     → celeste UEFA
//       MLS                  → verde
//       otras                → emerald default

const LEAGUE_COLORS: Record<string, string> = {
  // Football
  soccer_epl: "#6D28D9",                       // purple-700
  soccer_spain_la_liga: "#D97706",             // amber-600
  soccer_italy_serie_a: "#1D4ED8",             // blue-700
  soccer_italy_serie_b: "#60A5FA",             // blue-400
  soccer_germany_bundesliga: "#B91C1C",        // red-700
  soccer_france_ligue_one: "#0EA5E9",          // sky-500
  soccer_uefa_champs_league: "#0891B2",        // cyan-600
  soccer_uefa_europa_league: "#F97316",        // orange-500
  soccer_usa_mls: "#10B981",                   // emerald-500
  soccer_england_championship: "#A855F7",      // purple-500
  soccer_brazil_campeonato: "#059669",         // emerald-600
  soccer_argentina_primera_division: "#38BDF8",// sky-400
  soccer_chile_campeonato: "#DC2626",          // red-600
  soccer_netherlands_eredivisie: "#F59E0B",    // amber-500
  soccer_portugal_primeira_liga: "#84CC16",    // lime-500
  soccer_spain_segunda_division: "#EAB308",    // yellow-500
  soccer_england_efl_womens: "#EC4899",        // pink-500
  soccer_usa_nwsl: "#F472B6",                  // pink-400
};

const SPORT_COLORS: Record<string, string> = {
  baseball: "#DC2626",          // red-600
  basketball: "#F97316",        // orange-500
  icehockey: "#06B6D4",         // cyan-500
  americanfootball: "#CA8A04",  // yellow-600
  football: "#10B981",          // emerald-500 (fallback si liga no mapeada)
};

const FALLBACK = "#6B7280"; // gray-500

export function sportAccentColor(sport: string, league: string): string {
  return LEAGUE_COLORS[league] ?? SPORT_COLORS[sport] ?? FALLBACK;
}
