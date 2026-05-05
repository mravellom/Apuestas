"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Header } from "@/components/Header";
import { listArbitrageHistory, listOpportunityHistory } from "@/lib/api";
import { isAuthenticated } from "@/lib/auth";
import { sportAccentColor } from "@/lib/sportColors";
import type {
  ArbitrageHistoryItem,
  ArbitrageHistoryStatus,
  OpportunityHistoryItem,
} from "@/lib/types";

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

type Filter = "all" | ArbitrageHistoryStatus;

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Todos" },
  { key: "active", label: "Activos" },
  { key: "dead", label: "Muertos" },
  { key: "expired", label: "Expirados" },
];

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export default function ArbitrageHistoryPage() {
  const router = useRouter();
  const [items, setItems] = useState<ArbitrageHistoryItem[]>([]);
  const [valueBets, setValueBets] = useState<OpportunityHistoryItem[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const arbStatus = filter === "all" ? undefined : filter;
      const dateFilters = {
        fromDate: fromDate || undefined,
        toDate: toDate || undefined,
      };
      // Value bets no tienen estado "dead"; en ese filtro devolvemos vacío.
      const vbQuery =
        filter === "dead"
          ? Promise.resolve([] as OpportunityHistoryItem[])
          : listOpportunityHistory({
              status: filter === "all" ? undefined : filter,
              limit: 500,
              ...dateFilters,
            });
      const [arbs, vbs] = await Promise.all([
        listArbitrageHistory({ status: arbStatus, limit: 500, ...dateFilters }),
        vbQuery,
      ]);
      setItems(arbs);
      setValueBets(vbs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error cargando historial");
      setItems([]);
      setValueBets([]);
    } finally {
      setLoading(false);
    }
  }, [filter, fromDate, toDate]);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    void load();
  }, [load, router]);

  function applyPreset(preset: "today" | "7d" | "30d" | "clear") {
    if (preset === "clear") {
      setFromDate("");
      setToDate("");
      return;
    }
    const today = todayIso();
    setToDate(today);
    setFromDate(preset === "today" ? today : daysAgoIso(preset === "7d" ? 6 : 29));
  }

  const counts = useMemo(() => {
    const c = { total: items.length, active: 0, dead: 0, expired: 0 };
    for (const it of items) {
      if (it.status === "active") c.active += 1;
      else if (it.status === "dead") c.dead += 1;
      else if (it.status === "expired") c.expired += 1;
    }
    return c;
  }, [items]);

  return (
    <div className="min-h-screen">
      <Header />

      <main className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-white">Historial</h1>
          <p className="mt-1 text-sm text-muted">
            Todas las detecciones del motor. Primero arbitrajes, después value
            bets. Los marcados como
            <Badge status="dead" /> ya no son ejecutables porque las cuotas se
            movieron. Los <Badge status="expired" /> superaron el kickoff.
          </p>
        </div>

        <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard label="Total" value={String(counts.total)} />
          <StatCard label="Activos" value={String(counts.active)} highlight />
          <StatCard label="Muertos" value={String(counts.dead)} />
          <StatCard label="Expirados" value={String(counts.expired)} />
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={`rounded border px-3 py-1 text-sm transition ${
                filter === f.key
                  ? "border-accent bg-accent/20 text-accent"
                  : "border-border text-muted hover:border-accent hover:text-accent"
              }`}
            >
              {f.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="ml-auto rounded border border-border px-3 py-1 text-sm text-muted hover:border-accent hover:text-accent disabled:opacity-50"
          >
            {loading ? "Cargando…" : "Refrescar"}
          </button>
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-2 rounded border border-border bg-surface p-3">
          <span className="text-xs uppercase tracking-wide text-muted">Fecha</span>
          <label className="flex items-center gap-1 text-xs text-muted">
            Desde
            <input
              type="date"
              value={fromDate}
              max={toDate || undefined}
              onChange={(e) => setFromDate(e.target.value)}
              className="rounded border border-border bg-bg px-2 py-1 text-sm text-white"
            />
          </label>
          <label className="flex items-center gap-1 text-xs text-muted">
            Hasta
            <input
              type="date"
              value={toDate}
              min={fromDate || undefined}
              onChange={(e) => setToDate(e.target.value)}
              className="rounded border border-border bg-bg px-2 py-1 text-sm text-white"
            />
          </label>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => applyPreset("today")}
              className="rounded border border-border px-2 py-1 text-xs text-muted hover:border-accent hover:text-accent"
            >
              Hoy
            </button>
            <button
              type="button"
              onClick={() => applyPreset("7d")}
              className="rounded border border-border px-2 py-1 text-xs text-muted hover:border-accent hover:text-accent"
            >
              7d
            </button>
            <button
              type="button"
              onClick={() => applyPreset("30d")}
              className="rounded border border-border px-2 py-1 text-xs text-muted hover:border-accent hover:text-accent"
            >
              30d
            </button>
            <button
              type="button"
              onClick={() => applyPreset("clear")}
              className="rounded border border-border px-2 py-1 text-xs text-muted hover:border-accent hover:text-accent"
            >
              Limpiar
            </button>
          </div>
        </div>

        {error ? (
          <div className="mb-4 rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        <h2 className="mb-3 text-lg font-semibold text-white">Arbitrajes</h2>
        {items.length === 0 && !loading ? (
          <div className="rounded-lg border border-border bg-surface p-8 text-center text-muted">
            No hay arbitrajes con el filtro seleccionado.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border bg-surface">
            <table className="w-full text-sm">
              <thead className="bg-black/20 text-xs uppercase tracking-wide text-muted">
                <tr>
                  <Th>ID</Th>
                  <Th>Liga</Th>
                  <Th>Partido</Th>
                  <Th>Mercado</Th>
                  <Th className="text-right">Profit</Th>
                  <Th className="text-right">Legs</Th>
                  <Th>Estado</Th>
                  <Th>Detectado</Th>
                  <Th>Cerrado</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => {
                  const accent = sportAccentColor(it.sport, it.league);
                  return (
                    <tr
                      key={it.id}
                      className="border-t border-border text-white hover:bg-white/5"
                      style={{ boxShadow: `inset 4px 0 0 ${accent}` }}
                    >
                      <Td className="font-mono text-muted">#{it.id}</Td>
                      <Td>
                        <span
                          className="inline-block rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white"
                          style={{ backgroundColor: accent }}
                          title={`${it.sport} · ${it.league}`}
                        >
                          {prettyLeague(it.league, it.sport)}
                        </span>
                      </Td>
                      <Td>{it.match}</Td>
                      <Td className="text-muted">{it.market_type}</Td>
                      <Td className="text-right font-mono text-accent">
                        +{it.profit_pct.toFixed(2)}%
                      </Td>
                      <Td className="text-right font-mono text-muted">{it.num_legs}</Td>
                      <Td>
                        <Badge status={it.status} />
                      </Td>
                      <Td className="text-muted">{it.detected_at}</Td>
                      <Td className="text-muted">{it.closed_at ?? "—"}</Td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <h2 className="mb-3 mt-10 text-lg font-semibold text-white">
          Value bets <span className="text-xs font-normal text-muted">(detección actualmente pausada)</span>
        </h2>
        {valueBets.length === 0 && !loading ? (
          <div className="rounded-lg border border-border bg-surface p-8 text-center text-muted">
            No hay value bets con el filtro seleccionado.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border bg-surface">
            <table className="w-full text-sm">
              <thead className="bg-black/20 text-xs uppercase tracking-wide text-muted">
                <tr>
                  <Th>ID</Th>
                  <Th>Liga</Th>
                  <Th>Partido</Th>
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
                {valueBets.map((vb) => {
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
                        <Badge status={vb.status as ArbitrageHistoryStatus} />
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

function Badge({ status }: { status: ArbitrageHistoryStatus }) {
  const styles: Record<ArbitrageHistoryStatus, string> = {
    active: "border-accent/40 bg-accent/10 text-accent",
    dead: "border-danger/40 bg-danger/10 text-danger",
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
