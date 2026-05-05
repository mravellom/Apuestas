"use client";

import { clearToken, getToken } from "./auth";
import type {
  Arbitrage,
  ArbitrageHistoryItem,
  ArbitrageHistoryStatus,
  Bankroll,
  Bet,
  BetResult,
  BetStatus,
  CurrentUser,
  DailyPlan,
  ExecutionPlan,
  ExposureSummary,
  LoginResponse,
  OpportunityHistoryItem,
  OpportunityHistoryStatus,
  PaperBet,
  PaperCLV,
  PaperStats,
  RevalidationResult,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(`${API_URL}${path}`, { ...init, headers });

  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined" && !path.startsWith("/api/v1/auth")) {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Unauthorized");
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function getMe(): Promise<CurrentUser> {
  return request<CurrentUser>("/api/v1/auth/me");
}

export interface ArbitrageFilters {
  status?: "active" | "expired";
  minProfit?: number;
}

export async function listArbitrage(
  filters: ArbitrageFilters = {},
): Promise<Arbitrage[]> {
  const params = new URLSearchParams();
  params.set("status", filters.status ?? "active");
  if (filters.minProfit !== undefined) {
    params.set("min_profit", String(filters.minProfit));
  }
  return request<Arbitrage[]>(`/api/v1/arbitrage/?${params.toString()}`);
}

export interface ArbitrageHistoryFilters {
  status?: ArbitrageHistoryStatus;
  limit?: number;
  fromDate?: string;
  toDate?: string;
}

export async function listArbitrageHistory(
  filters: ArbitrageHistoryFilters = {},
): Promise<ArbitrageHistoryItem[]> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  params.set("limit", String(filters.limit ?? 200));
  if (filters.fromDate) params.set("from_date", filters.fromDate);
  if (filters.toDate) params.set("to_date", filters.toDate);
  return request<ArbitrageHistoryItem[]>(
    `/api/v1/arbitrage/history?${params.toString()}`,
  );
}

export interface OpportunityHistoryFilters {
  status?: OpportunityHistoryStatus;
  limit?: number;
  fromDate?: string;
  toDate?: string;
}

export async function listOpportunityHistory(
  filters: OpportunityHistoryFilters = {},
): Promise<OpportunityHistoryItem[]> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  params.set("limit", String(filters.limit ?? 200));
  if (filters.fromDate) params.set("from_date", filters.fromDate);
  if (filters.toDate) params.set("to_date", filters.toDate);
  return request<OpportunityHistoryItem[]>(
    `/api/v1/opportunities/history?${params.toString()}`,
  );
}

export async function getArbitrage(id: number): Promise<Arbitrage | null> {
  // Backend has no /arbitrage/{id} endpoint; filter client-side from the list.
  const all = await listArbitrage({ status: "active" });
  const found = all.find((a) => a.id === id);
  if (found) return found;
  const expired = await listArbitrage({ status: "expired" });
  return expired.find((a) => a.id === id) ?? null;
}

export interface PaperBetFilters {
  result?: "pending" | "won" | "lost" | "void";
  sourceType?: "value" | "arbitrage";
  limit?: number;
}

export async function listPaperBets(filters: PaperBetFilters = {}): Promise<PaperBet[]> {
  const params = new URLSearchParams();
  if (filters.result) params.set("result", filters.result);
  if (filters.sourceType) params.set("source_type", filters.sourceType);
  params.set("limit", String(filters.limit ?? 100));
  return request<PaperBet[]>(`/api/v1/paper/bets?${params.toString()}`);
}

export async function getPaperStats(sourceType?: "value" | "arbitrage"): Promise<PaperStats> {
  const qs = sourceType ? `?source_type=${sourceType}` : "";
  return request<PaperStats>(`/api/v1/paper/stats${qs}`);
}

export interface CLVFilters {
  sourceType?: "value" | "arbitrage";
  bookmakerKey?: string;
  result?: "pending" | "won" | "lost" | "void";
}

export async function getPaperCLV(filters: CLVFilters = {}): Promise<PaperCLV> {
  const params = new URLSearchParams();
  if (filters.sourceType) params.set("source_type", filters.sourceType);
  if (filters.bookmakerKey) params.set("bookmaker_key", filters.bookmakerKey);
  if (filters.result) params.set("result", filters.result);
  const qs = params.toString();
  return request<PaperCLV>(`/api/v1/paper/clv${qs ? `?${qs}` : ""}`);
}

export async function listBankrolls(): Promise<Bankroll[]> {
  return request<Bankroll[]>("/api/v1/users/bankroll");
}

export async function createBankroll(input: {
  name?: string;
  currency?: string;
  initial_amount: number;
}): Promise<Bankroll> {
  return request<Bankroll>("/api/v1/users/bankroll", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function revalidateArbitrage(arbId: number): Promise<RevalidationResult> {
  return request<RevalidationResult>(`/api/v1/arbitrage/${arbId}/revalidate`);
}

export async function getArbitrageExposure(arbId: number): Promise<ExposureSummary> {
  return request<ExposureSummary>(`/api/v1/arbitrage/${arbId}/exposure`);
}

export interface DailyPlanParams {
  bankrollId: number;
  dailyCap?: number;
  targetPct?: number;
  maxStakePerArbPct?: number;
}

export async function getDailyPlan(params: DailyPlanParams): Promise<DailyPlan> {
  const query = new URLSearchParams();
  query.set("bankroll_id", String(params.bankrollId));
  if (params.dailyCap !== undefined) query.set("daily_cap", String(params.dailyCap));
  if (params.targetPct !== undefined) query.set("target_pct", String(params.targetPct));
  if (params.maxStakePerArbPct !== undefined) {
    query.set("max_stake_per_arb_pct", String(params.maxStakePerArbPct));
  }
  return request<DailyPlan>(`/api/v1/planning/daily?${query.toString()}`);
}

export async function executeArbitrage(
  arbId: number,
  bankrollId: number,
  totalStake: number,
  forceIfStale = false,
): Promise<ExecutionPlan> {
  return request<ExecutionPlan>(`/api/v1/arbitrage/${arbId}/execute`, {
    method: "POST",
    body: JSON.stringify({
      bankroll_id: bankrollId,
      total_stake: totalStake,
      force_if_stale: forceIfStale,
    }),
  });
}

export async function placeBet(betId: number, oddsAtPlacement: number): Promise<Bet> {
  return request<Bet>(`/api/v1/bets/${betId}/place`, {
    method: "PATCH",
    body: JSON.stringify({ odds_at_placement: oddsAtPlacement }),
  });
}

export async function rejectBet(betId: number, reason = ""): Promise<Bet> {
  return request<Bet>(`/api/v1/bets/${betId}/reject`, {
    method: "PATCH",
    body: JSON.stringify({ reason }),
  });
}

export async function settleBet(
  betId: number,
  result: BetResult,
  actualPayout: number,
): Promise<Bet> {
  return request<Bet>(`/api/v1/bets/${betId}/settle`, {
    method: "PATCH",
    body: JSON.stringify({ result, actual_payout: actualPayout }),
  });
}

export interface BetFilters {
  status?: BetStatus;
  arbitrageId?: number;
  limit?: number;
}

export async function listBets(filters: BetFilters = {}): Promise<Bet[]> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status_filter", filters.status);
  if (filters.arbitrageId !== undefined) {
    params.set("arbitrage_id", String(filters.arbitrageId));
  }
  params.set("limit", String(filters.limit ?? 50));
  return request<Bet[]>(`/api/v1/bets?${params.toString()}`);
}
