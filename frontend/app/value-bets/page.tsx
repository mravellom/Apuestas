"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Header } from "@/components/Header";
import { listOpportunityHistory } from "@/lib/api";
import { isAuthenticated } from "@/lib/auth";
import { sportAccentColor } from "@/lib/sportColors";
import type { OpportunityHistoryItem } from "@/lib/types";

const LEAGUE_LABELS: Record<string, string> = {
  soccer_epl: "EPL",
  soccer_spain_la_liga: "La Liga",
  soccer_italy_serie_a: "Serie A",
  soccer_italy_serie_b: "Serie B",
  soccer_germany_bundesliga: "Bundesliga",
  soccer_france_ligue_one: "Ligue 1",
  soccer_uefa_champs_league: "UCL",
  soccer_uefa_europa_league: "UEL",
  soccer_usa_mls: "MLS",
  soccer_england_championship: "Championship",
  soccer_brazil_campeonato: "Brasileirão",
  soccer_argentina_primera_division: "Arg Primera",
  soccer_chile_campeonato: "Chile",
  soccer_netherlands_eredivisie: "Eredivisie",
  soccer_portugal_primeira_liga: "Primeira",
  soccer_spain_segunda_division: "Segunda",
  soccer_england_efl_womens: "EFL W",
  soccer_usa_nwsl: "NWSL",
  baseball_mlb: "MLB",
  basketball_nba: "NBA",
  basketball_wnba: "WNBA",
  icehockey_nhl: "NHL",
  americanfootball_nfl: "NFL",
};

function prettyLeague(league: string, sport: string): string {
  return LEAGUE_LABELS[league] ?? sport.toUpperCase();
}

type StatusFilter = "active" | "expired" | "all";

const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: "active", label: "Activas" },
  { key: "expired", label: "Expiradas" },
  { key: "all", label: "Todas" },
];

type SortKey = "ev" | "odds" | "kickoff" | "detected";

export default function ValueBetsPage() {
  const router = useRouter();
  const [items, setItems] = useState<OpportunityHistoryItem[]>([]);
  const [status, setStatus] = useState<StatusFilter>("active");
  const [minEv, setMinEv] = useState(0);
  const [sport, setSport] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("ev");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listOpportunityHistory({
        status: status === "all" ? undefined : status,
        limit: 500,
      });
      setItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error cargando value bets");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    void load();
  }, [load, router]);

  // Auto-refresh cada 60s solo cuando se ven activas
  useEffect(() => {
    if (status !== "active") return;
    const id = window.setInterval(() => {
      if (isAuthenticated()) void load();
    }, 60_000);
    return () => window.clearInterval(id);
  }, [load, status]);

  const sportsAvailable = useMemo(() => {
    const set = new Set<string>();
    for (const it of items) set.add(it.sport);
    return Array.from(set).sort();
  }, [items]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = items.filter((it) => {
      if (sport !== "all" && it.sport !== sport) return false;
      if (it.value_pct * 100 < minEv) return false;
      if (q && !it.match.toLowerCase().includes(q)) return false;
      return true;
    });
    list.sort((a, b) => {
      switch (sortBy) {
        case "ev":
          return b.value_pct - a.value_pct;
        case "odds":
          return b.odds_price - a.odds_price;
        case "kickoff":
          return a.commence_time.localeCompare(b.commence_time);
        case "detected":
          return b.detected_at.localeCompare(a.detected_at);
      }
    });
    return list;
  }, [items, minEv, sport, search, sortBy]);

  const stats = useMemo(() => {
    if (filtered.length === 0) return null;
    const evs = filtered.map((it) => it.value_pct * 100);
    const best = Math.max(...evs);
    const avg = evs.reduce((s, v) => s + v, 0) / evs.length;
    const steam = filtered.filter((it) => it.kelly_stake_pct !== null && it.kelly_stake_pct > 0.01).length;
    return { count: filtered.length, best, avg, steam };
  }, [filtered]);

  return (
    <div className="min-h-screen">
      <Header />

      <main className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-white">Value bets</h1>
          <p className="mt-1 text-sm text-muted">
            Cuotas con valor esperado positivo contra el consenso de mercado
            (corregido por vig). Ordenadas por EV. La columna Kelly muestra el
            % de bankroll sugerido por la fracción configurada por el usuario.
          </p>
        </div>

        {stats ? (
          <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Resultados" value={String(stats.count)} />
            <StatCard label="Mejor EV" value={`+${stats.best.toFixed(2)}%`} highlight />
            <StatCard label="EV medio" value={`+${stats.avg.toFixed(2)}%`} />
            <StatCard label="Kelly ≥ 1%" value={String(stats.steam)} />
          </div>
        ) : null}

        <div className="mb-4 flex flex-wrap items-center gap-2">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setStatus(f.key)}
              className={`rounded border px-3 py-1 text-sm transition ${
                status === f.key
                  ? "border-accent bg-accent/20 text-accent"
                  : "border-border text-muted hover:border-accent hover:text-accent"
              }`}
            >
              {f.label}
            </button>
          ))}

          <div className="ml-2 flex items-center gap-2 text-sm text-muted">
            <label htmlFor="min-ev">EV mín %</label>
            <input
              id="min-ev"
              type="number"
              min={0}
              step={0.5}
              value={minEv}
              onChange={(e) => setMinEv(Number(e.target.value) || 0)}
              className="w-16 rounded border border-border bg-surface px-2 py-1 text-right font-mono text-white"
            />
          </div>

          <select
            value={sport}
            onChange={(e) => setSport(e.target.value)}
            className="rounded border border-border bg-surface px-2 py-1 text-sm text-white"
          >
            <option value="all">Todos los deportes</option>
            {sportsAvailable.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>

          <input
            type="search"
            placeholder="Buscar equipo…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="rounded border border-border bg-surface px-3 py-1 text-sm text-white placeholder:text-muted"
          />

          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortKey)}
            className="rounded border border-border bg-surface px-2 py-1 text-sm text-white"
          >
            <option value="ev">Ordenar: EV</option>
            <option value="odds">Ordenar: cuota</option>
            <option value="kickoff">Ordenar: kickoff</option>
            <option value="detected">Ordenar: detección</option>
          </select>

          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="ml-auto rounded border border-border px-3 py-1 text-sm text-muted hover:border-accent hover:text-accent disabled:opacity-50"
          >
            {loading ? "Cargando…" : "Refrescar"}
          </button>
        </div>

        {error ? (
          <div className="mb-4 rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        {filtered.length === 0 && !loading ? (
          <div className="rounded-lg border border-border bg-surface p-8 text-center text-muted">
            No hay value bets con los filtros seleccionados.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border bg-surface">
            <table className="w-full text-sm">
              <thead className="bg-black/20 text-xs uppercase tracking-wide text-muted">
                <tr>
                  <Th>ID</Th>
                  <Th>Liga</Th>
                  <Th>Partido</Th>
                  <Th>Kickoff</Th>
                  <Th>Pick</Th>
                  <Th>Book</Th>
                  <Th className="text-right">Cuota</Th>
                  <Th className="text-right">EV</Th>
                  <Th className="text-right">Kelly</Th>
                  <Th>Estado</Th>
                  <Th>Detectado</Th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((vb) => {
                  const accent = sportAccentColor(vb.sport, vb.league);
                  return (
                    <tr
                      key={vb.id}
                      className="border-t border-border text-white hover:bg-white/5"
                      style={{ boxShadow: `inset 4px 0 0 ${accent}` }}
                    >
                      <Td className="font-mono text-muted">#{vb.id}</Td>
                      <Td>
                        <span
                          className="inline-block rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white"
                          style={{ backgroundColor: accent }}
                          title={`${vb.sport} · ${vb.league}`}
                        >
                          {prettyLeague(vb.league, vb.sport)}
                        </span>
                      </Td>
                      <Td>{vb.match}</Td>
                      <Td className="text-muted">{vb.commence_time}</Td>
                      <Td className="text-white">{vb.outcome_name}</Td>
                      <Td className="font-mono uppercase text-muted">{vb.bookmaker}</Td>
                      <Td className="text-right font-mono">{vb.odds_price.toFixed(2)}</Td>
                      <Td className="text-right font-mono text-accent">
                        +{(vb.value_pct * 100).toFixed(2)}%
                      </Td>
                      <Td className="text-right font-mono text-muted">
                        {vb.kelly_stake_pct === null
                          ? "—"
                          : `${(vb.kelly_stake_pct * 100).toFixed(2)}%`}
                      </Td>
                      <Td>
                        <Badge status={vb.status} />
                      </Td>
                      <Td className="text-muted">{vb.detected_at}</Td>
                    </tr>
                  );
                })}
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
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div
        className={`mt-1 font-mono text-2xl ${highlight ? "text-accent" : "text-white"}`}
      >
        {value}
      </div>
    </div>
  );
}

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <th className={`px-3 py-2 text-left font-medium ${className}`}>{children}</th>;
}

function Td({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <td className={`px-3 py-2 ${className}`}>{children}</td>;
}

function Badge({ status }: { status: "active" | "expired" }) {
  const styles: Record<"active" | "expired", string> = {
    active: "border-accent/40 bg-accent/10 text-accent",
    expired: "border-border bg-white/5 text-muted",
  };
  return (
    <span
      className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${styles[status]}`}
    >
      {status}
    </span>
  );
}
