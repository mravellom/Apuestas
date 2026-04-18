// Tipos espejados del backend (app/api/v1/arbitrage.py :: ArbResponse).

export interface ArbitrageLeg {
  outcome: string;
  outcome_name: string;
  bookmaker: string;
  odds: number;
  stake_pct: number;
}

export interface Arbitrage {
  id: number;
  match: string;
  commence_time: string;
  market_type: string;
  profit_pct: number;
  total_implied: number;
  legs: ArbitrageLeg[];
  status: "active" | "expired";
  detected_at: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
}

export interface CurrentUser {
  id: string;
  email: string;
  username: string;
  role: "free" | "premium" | "admin";
  is_active: boolean;
}

export interface PaperBet {
  id: number;
  source_type: "value" | "arbitrage";
  match: string;
  outcome: string;
  bookmaker: string;
  odds_taken: number;
  stake_units: number;
  ev_at_placement: number | null;
  placed_at: string;
  result: "pending" | "won" | "lost" | "void";
  profit_units: number | null;
}

export interface PaperStats {
  total_bets: number;
  pending: number;
  won: number;
  lost: number;
  void: number;
  total_staked_units: number;
  total_profit_units: number;
  roi_pct: number | null;
  win_rate_pct: number | null;
  by_source: Record<string, { bets: number; profit_units: number }>;
  by_bookmaker: Record<string, { bets: number; profit_units: number }>;
}
