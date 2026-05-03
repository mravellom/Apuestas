"use client";

const TOKEN_KEY = "vb_token";

/**
 * Token dev embebido: JWT de un año para el user admin owner@valuebet.app.
 * Modo single-user local — NO usar en prod. Si está seteado, el frontend
 * omite el flow de login y va directo al dashboard.
 * Para reactivar login: borrar NEXT_PUBLIC_DEV_TOKEN del .env.local.
 */
const DEV_TOKEN =
  process.env.NEXT_PUBLIC_DEV_TOKEN ??
  (typeof window !== "undefined" ? "" : "");

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  const stored = window.localStorage.getItem(TOKEN_KEY);
  if (stored) return stored;
  if (DEV_TOKEN) return DEV_TOKEN;
  return null;
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}
