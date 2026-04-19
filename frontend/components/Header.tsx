"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { clearToken } from "@/lib/auth";

export function Header() {
  const router = useRouter();

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

  return (
    <header className="border-b border-border bg-surface">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <Link href="/arbitrage" className="text-lg font-bold text-accent">
          ValueBet · Arbitraje
        </Link>
        <nav className="flex items-center gap-6 text-sm">
          <Link href="/arbitrage" className="text-muted hover:text-white">
            Oportunidades
          </Link>
          <Link href="/planning" className="text-muted hover:text-white">
            Plan diario
          </Link>
          <Link href="/bets" className="text-muted hover:text-white">
            Mis apuestas
          </Link>
          <Link href="/bankroll" className="text-muted hover:text-white">
            Bankroll
          </Link>
          <Link href="/paper" className="text-muted hover:text-white">
            Paper
          </Link>
          <button
            type="button"
            onClick={handleLogout}
            className="rounded border border-border px-3 py-1 text-muted hover:border-accent hover:text-accent"
          >
            Cerrar sesión
          </button>
        </nav>
      </div>
    </header>
  );
}
