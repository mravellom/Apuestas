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

export interface AllocationSuggestion {
  arbitrage_id: number;
  match_label: string;
  market_type: string;
  profit_pct: number;
  suggested_stake: number;
  expected_profit: number;
  bookmakers: string[];
}

export interface DailyPlan {
  currency: string;
  daily_investment_cap: number;
  target_pct: number;
  target_profit: number;
  max_stake_per_arb_pct: number;
  available_arbs: number;
  allocations: AllocationSuggestion[];
  total_suggested_stake: number;
  expected_total_profit: number;
  target_coverage_pct: number;
  status: "empty" | "unachievable" | "achievable" | "exceeded";
  recommendation: string;
}

export interface Bankroll {
  id: number;
  name: string;
  currency: string;
  initial_amount: number;
  current_amount: number;
  reserved_amount: number;
  available_amount: number;
}

export interface LegInstruction {
  bet_id: number;
  bookmaker_key: string;
  bookmaker_name: string;
  outcome_key: string;
  outcome_name: string;
  stake_amount: number;
  target_odds: number;
  min_acceptable_odds: number;
  commission_pct: number;
}

export interface ExecutionPlan {
  arbitrage_id: number;
  match_label: string;
  market_type: string;
  total_stake: number;
  currency: string;
  expected_profit: number;
  profit_pct: number;
  legs: LegInstruction[];
}

export type BetStatus =
  | "pending"
  | "placed"
  | "confirmed"
  | "rejected"
  | "void"
  | "settled";

export type BetResult = "won" | "lost" | "void" | "half_won" | "half_lost";

export interface RevalidationResult {
  status: "alive" | "stale" | "dead";
  detected_profit_pct: number;
  current_profit_pct: number;
  age_seconds: number;
  current_legs: ArbitrageLeg[] | null;
}

export interface OutcomeScenario {
  outcome_key: string;
  outcome_name: string;
  pnl: number;
  covered: boolean;
}

export interface LegSummary {
  bet_id: number;
  outcome_key: string;
  outcome_name: string;
  bookmaker_key: string;
  bookmaker_name: string;
  stake_amount: number;
  status: BetStatus;
  odds_effective: number | null;
  commission_pct: number;
}

export interface ReplacementOption {
  bookmaker_key: string;
  bookmaker_name: string;
  odds: number;
  commission_pct: number;
}

export interface ReplacementSuggestion {
  outcome_key: string;
  outcome_name: string;
  rejected_bookmaker_key: string;
  alternatives: ReplacementOption[];
}

export interface ExposureSummary {
  arbitrage_id: number;
  currency: string;
  is_partial_fill: boolean;
  any_rejected: boolean;
  all_placed: boolean;
  total_placed_stake: number;
  worst_case_pnl: number;
  best_case_pnl: number;
  scenarios: OutcomeScenario[];
  legs: LegSummary[];
  replacement_suggestions: ReplacementSuggestion[];
}

export interface Bet {
  id: number;
  arbitrage_id: number | null;
  opportunity_id: number | null;
  bookmaker_id: number;
  outcome_id: number;
  stake_amount: number;
  odds_at_detection: number | null;
  odds_at_placement: number | null;
  commission_pct: number;
  status: BetStatus;
  result: BetResult | null;
  actual_payout: number | null;
  profit_loss: number | null;
  created_at: string;
  placed_at: string | null;
  settled_at: string | null;
}
