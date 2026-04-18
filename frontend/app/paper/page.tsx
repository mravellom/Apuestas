"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Header } from "@/components/Header";
import { getPaperStats, listPaperBets } from "@/lib/api";
import { isAuthenticated } from "@/lib/auth";
import type { PaperBet, PaperStats } from "@/lib/types";

type ResultFilter = "all" | "pending" | "won" | "lost";

export default function PaperTradingPage() {
  const router = useRouter();
  const [stats, setStats] = useState<PaperStats | null>(null);
  const [bets, setBets] = useState<PaperBet[]>([]);
  const [filter, setFilter] = useState<ResultFilter>("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, b] = await Promise.all([
        getPaperStats(),
        listPaperBets({ result: filter === "all" ? undefined : filter, limit: 200 }),
      ]);
      setStats(s);
      setBets(b);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error cargando paper trading");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    void load();
  }, [load, router]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (isAuthenticated()) void load();
    }, 60_000);
    return () => window.clearInterval(id);
  }, [load]);

  return (
    <div className="min-h-screen">
      <Header />
      <main className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-white">Paper trading</h1>
          <p className="mt-1 text-sm text-muted">
            Apuestas simuladas registradas automáticamente por el engine. Validan si el
            edge es real antes de arriesgar dinero. Stakes y profits en unidades de
            bankroll (0.01 = 1%).
          </p>
        </div>

        {stats ? (
          <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Total bets" value={String(stats.total_bets)} />
            <StatCard
              label="ROI"
              value={stats.roi_pct === null ? "—" : `${stats.roi_pct >= 0 ? "+" : ""}${stats.roi_pct.toFixed(2)}%`}
              highlight={stats.roi_pct !== null && stats.roi_pct >= 0}
              negative={stats.roi_pct !== null && stats.roi_pct < 0}
            />
            <StatCard
              label="Win rate"
              value={stats.win_rate_pct === null ? "—" : `${stats.win_rate_pct.toFixed(1)}%`}
            />
            <StatCard
              label="Profit (u)"
              value={`${stats.total_profit_units >= 0 ? "+" : ""}${stats.total_profit_units.toFixed(4)}`}
              highlight={stats.total_profit_units > 0}
              negative={stats.total_profit_units < 0}
            />
          </div>
        ) : null}

        {stats ? (
          <div className="mb-6 grid grid-cols-4 gap-4">
            <PillCard label="Pending" value={stats.pending} />
            <PillCard label="Won" value={stats.won} />
            <PillCard label="Lost" value={stats.lost} />
            <PillCard label="Void" value={stats.void} />
          </div>
        ) : null}

        <div className="mb-4 flex items-center gap-2">
          {(["all", "pending", "won", "lost"] as ResultFilter[]).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={`rounded border px-3 py-1 text-xs uppercase tracking-wide ${
                filter === f
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border text-muted hover:text-white"
              }`}
            >
              {f}
            </button>
          ))}
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="ml-auto rounded border border-border px-3 py-1 text-xs text-muted hover:border-accent hover:text-accent disabled:opacity-50"
          >
            {loading ? "Cargando..." : "Refrescar"}
          </button>
        </div>

        {error ? (
          <div className="mb-4 rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        {bets.length === 0 && !loading ? (
          <div className="rounded-lg border border-border bg-surface p-8 text-center text-muted">
            No hay paper bets con este filtro.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border bg-surface">
            <table className="w-full text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-3 py-2 text-left">Placed</th>
                  <th className="px-3 py-2 text-left">Type</th>
                  <th className="px-3 py-2 text-left">Match</th>
                  <th className="px-3 py-2 text-left">Pick</th>
                  <th className="px-3 py-2 text-left">Book</th>
                  <th className="px-3 py-2 text-right">Odds</th>
                  <th className="px-3 py-2 text-right">Stake (u)</th>
                  <th className="px-3 py-2 text-right">EV</th>
                  <th className="px-3 py-2 text-center">Result</th>
                  <th className="px-3 py-2 text-right">P/L (u)</th>
                </tr>
              </thead>
              <tbody>
                {bets.map((b) => (
                  <tr key={b.id} className="border-b border-border/50 hover:bg-surface/60">
                    <td className="px-3 py-2 text-muted">{b.placed_at}</td>
                    <td className="px-3 py-2">{b.source_type}</td>
                    <td className="px-3 py-2 text-white">{b.match}</td>
                    <td className="px-3 py-2">{b.outcome}</td>
                    <td className="px-3 py-2 font-mono">{b.bookmaker}</td>
                    <td className="px-3 py-2 text-right font-mono">{b.odds_taken.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right font-mono">{b.stake_units.toFixed(4)}</td>
                    <td className="px-3 py-2 text-right font-mono">
                      {b.ev_at_placement === null ? "—" : `${(b.ev_at_placement * 100).toFixed(2)}%`}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <ResultBadge result={b.result} />
                    </td>
                    <td
                      className={`px-3 py-2 text-right font-mono ${
                        b.profit_units === null
                          ? "text-muted"
                          : b.profit_units > 0
                          ? "text-accent"
                          : b.profit_units < 0
                          ? "text-danger"
                          : ""
                      }`}
                    >
                      {b.profit_units === null
                        ? "—"
                        : `${b.profit_units >= 0 ? "+" : ""}${b.profit_units.toFixed(4)}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}

function StatCard({
  label,
  value,
  highlight = false,
  negative = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
  negative?: boolean;
}) {
  const color = negative ? "text-danger" : highlight ? "text-accent" : "text-white";
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 font-mono text-2xl ${color}`}>{value}</div>
    </div>
  );
}

function PillCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-border bg-surface p-3 text-center">
      <div className="text-xs uppercase text-muted">{label}</div>
      <div className="mt-1 font-mono text-lg text-white">{value}</div>
    </div>
  );
}

function ResultBadge({ result }: { result: PaperBet["result"] }) {
  const colors = {
    pending: "border-border text-muted",
    won: "border-accent/40 bg-accent/10 text-accent",
    lost: "border-danger/40 bg-danger/10 text-danger",
    void: "border-border bg-border/20 text-muted",
  };
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-xs ${colors[result]}`}>
      {result}
    </span>
  );
}
