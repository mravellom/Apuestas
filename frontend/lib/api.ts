"use client";

import { clearToken, getToken } from "./auth";
import type { Arbitrage, CurrentUser, LoginResponse } from "./types";

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

export async function getArbitrage(id: number): Promise<Arbitrage | null> {
  // Backend has no /arbitrage/{id} endpoint; filter client-side from the list.
  const all = await listArbitrage({ status: "active" });
  const found = all.find((a) => a.id === id);
  if (found) return found;
  const expired = await listArbitrage({ status: "expired" });
  return expired.find((a) => a.id === id) ?? null;
}
