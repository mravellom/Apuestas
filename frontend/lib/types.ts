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
