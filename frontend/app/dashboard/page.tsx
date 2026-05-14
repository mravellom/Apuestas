"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Header } from "@/components/Header";
import {
  getDailyDeployment,
  getDashboardSummary,
  listAdminLeagues,
  toggleLeague,
} from "@/lib/api";
import { isAuthenticated } from "@/lib/auth";
import { sportAccentColor } from "@/lib/sportColors";
import type {
  AdminLeague,
  DailyDeployment,
  DashboardSummary,
  HourBucket,
} from "@/lib/types";

const WINDOW_PRESETS: { label: string; days: number }[] = [
  { label: "1d", days: 1 },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
];

export default function DashboardPage() {
  const router = useRouter();
  const [windowDays, setWindowDays] = useState(7);
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [leagues, setLeagues] = useState<AdminLeague[]>([]);
  const [deployment, setDeployment] = useState<DailyDeployment | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [d, lg, dep] = await Promise.all([
        getDashboardSummary(windowDays),
        listAdminLeagues().catch(() => [] as AdminLeague[]),
        getDailyDeployment(windowDays).catch(() => null),
      ]);
      setData(d);
      setLeagues(lg);
      setDeployment(dep);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error cargando dashboard");
    } finally {
      setLoading(false);
    }
  }, [windowDays]);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    void load();
  }, [load, router]);

  async function handleToggleLeague(key: string, enabled: boolean) {
    // Optimistic update
    setLeagues((prev) =>
      prev.map((l) => (l.key === key ? { ...l, detection_enabled: enabled } : l)),
    );
    try {
      await toggleLeague(key, enabled);
      // Refresh summary so sport counts reflect the change
      const d = await getDashboardSummary(windowDays);
      setData(d);
    } catch (err) {
      // Revert
      setLeagues((prev) =>
        prev.map((l) => (l.key === key ? { ...l, detection_enabled: !enabled } : l)),
      );
      setError(
        err instanceof Error
          ? err.message
          : "Error cambiando estado de la liga",
      );
    }
  }

  return (
    <div className="min-h-screen">
      <Header />
      <main className="mx-auto max-w-6xl px-6 py-8 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-white">Dashboard</h1>
            <p className="mt-1 text-sm text-muted">
              Estado del motor: deportes activos, dónde aparecen los arbitrajes,
              qué casas dominan, consumo de la API.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-muted">Ventana</span>
            {WINDOW_PRESETS.map((p) => (
              <button
                key={p.days}
                type="button"
                onClick={() => setWindowDays(p.days)}
                className={`rounded border px-3 py-1 text-sm transition ${
                  windowDays === p.days
                    ? "border-accent bg-accent/20 text-accent"
                    : "border-border text-muted hover:border-accent hover:text-accent"
                }`}
              >
                {p.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading}
              className="ml-2 rounded border border-border px-3 py-1 text-sm text-muted hover:border-accent hover:text-accent disabled:opacity-50"
            >
              {loading ? "..." : "↻"}
            </button>
          </div>
        </div>

        {error ? (
          <div className="rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        {data ? (
          <>
            {deployment ? <DeploymentCard data={deployment} /> : null}
            <SportsCard data={data} />
            {leagues.length > 0 ? (
              <LeaguesPanel leagues={leagues} onToggle={handleToggleLeague} />
            ) : null}
            <div className="grid gap-6 lg:grid-cols-2">
              <TopLeaguesCard data={data} />
              <ApiUsageCard data={data} />
            </div>
            <div className="grid gap-6 lg:grid-cols-2">
              <TopBooksCard
                title="Casas con más arbitrajes"
                subtitle="Conteo de patas en arbs detectados"
                items={data.top_books_arbs}
                accent="#22c55e"
              />
              <TopBooksCard
                title="Casas con más value bets"
                subtitle="Conteo de oportunidades emitidas"
                items={data.top_books_valuebets}
                accent="#06b6d4"
              />
            </div>
            <div className="grid gap-6 lg:grid-cols-2">
              <HourDistributionCard
                title="Arbitrajes por hora"
                subtitle="Hora de detección (CLT, America/Santiago)"
                buckets={data.arbs_by_hour_clt}
                color="#22c55e"
              />
              <HourDistributionCard
                title="Value bets por hora"
                subtitle="Hora de detección (CLT, America/Santiago)"
                buckets={data.valuebets_by_hour_clt}
                color="#06b6d4"
              />
            </div>
            <p className="text-right text-xs text-muted">
              Generado {data.generated_at} · ventana últimos {data.window_days} días
            </p>
          </>
        ) : !loading ? (
          <div className="rounded border border-border bg-surface p-8 text-center text-muted">
            Sin datos.
          </div>
        ) : null}
      </main>
    </div>
  );
}

// ── Daily deployment (utilización banca) ────────────────────────────────────
function DeploymentCard({ data }: { data: DailyDeployment }) {
  const s = data.summary;
  const rowsWithActivity = data.rows.filter((r) => r.num_bets > 0);
  const fmt = (n: number) => n.toLocaleString("es-CL", { maximumFractionDigits: 2 });
  const pct = (n: number | null | undefined, digits = 2) =>
    n == null ? "—" : `${n.toFixed(digits)}%`;
  const ccy = s.bankroll_currency ?? "";

  return (
    <section className="rounded-lg border border-border bg-surface p-5">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-white">
            Banca desplegada por día
          </h2>
          <p className="text-xs text-muted">
            Cuánta banca real puso a trabajar (`bet_tracking`) vs banca actual.
            Mide utilización efectiva, no edge teórico.
          </p>
        </div>
        <span className="text-xs text-muted">
          Banca total{" "}
          <span className="font-mono text-white">
            {fmt(s.bankroll_total)} {ccy}
          </span>
        </span>
      </div>

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric
          label="Utilización promedio"
          value={pct(s.avg_utilization_pct, 2)}
          hint={`${s.days_with_activity} de ${data.window_days} días con apuestas`}
        />
        <Metric
          label="Edge teórico promedio"
          value={pct(s.avg_theoretical_edge_pct, 3)}
          hint="por arb tocado"
          accent="#06b6d4"
        />
        <Metric
          label="ROI realizado periodo"
          value={pct(s.realized_roi_pct, 3)}
          hint={s.realized_roi_pct == null ? "sin liquidados" : "sobre stake liquidado"}
          accent={
            s.realized_roi_pct == null
              ? undefined
              : s.realized_roi_pct >= 0
                ? "#22c55e"
                : "#ef4444"
          }
        />
        <Metric
          label="Stake / Profit"
          value={`${fmt(s.total_stake_period)} / ${fmt(s.total_realized_profit)}`}
          hint={ccy || undefined}
        />
      </div>

      {rowsWithActivity.length === 0 ? (
        <div className="rounded border border-border/60 bg-bg p-4 text-sm text-muted">
          Sin apuestas reales registradas en la ventana. Cuando empieces a usar{" "}
          <code className="font-mono text-white">/arbitrage/{`{id}`}/execute</code>{" "}
          y confirmes en <code className="font-mono text-white">bet_tracking</code>,
          aparecerán acá. (Hay {s.days_with_activity === 0 ? "0" : s.days_with_activity}{" "}
          días con actividad en los últimos {data.window_days}).
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-[10px] uppercase tracking-wide text-muted">
              <tr className="border-b border-border">
                <th className="py-2 pr-3 text-left">Fecha</th>
                <th className="py-2 pr-3 text-right">Arbs</th>
                <th className="py-2 pr-3 text-right">Bets</th>
                <th className="py-2 pr-3 text-right">Stake</th>
                <th className="py-2 pr-3 text-right">Util %</th>
                <th className="py-2 pr-3 text-right">Edge teórico</th>
                <th className="py-2 pr-3 text-right">ROI realizado</th>
                <th className="py-2 pr-3 text-right">Liq / Pend</th>
              </tr>
            </thead>
            <tbody>
              {rowsWithActivity.map((r) => (
                <tr key={r.date} className="border-b border-border/40">
                  <td className="py-2 pr-3 font-mono text-white">{r.date}</td>
                  <td className="py-2 pr-3 text-right font-mono text-white">
                    {r.num_arbs}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-muted">
                    {r.num_bets}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-white">
                    {fmt(r.total_stake)}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono">
                    <span
                      className={
                        (r.utilization_pct ?? 0) > 80
                          ? "text-warn"
                          : "text-accent"
                      }
                    >
                      {pct(r.utilization_pct, 2)}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-muted">
                    {pct(r.theoretical_edge_avg_pct, 3)}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono">
                    <span
                      className={
                        r.realized_roi_pct == null
                          ? "text-muted"
                          : r.realized_roi_pct >= 0
                            ? "text-accent"
                            : "text-danger"
                      }
                    >
                      {pct(r.realized_roi_pct, 3)}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-muted">
                    {r.settled_bets} / {r.pending_bets}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Metric({
  label,
  value,
  hint,
  accent,
}: {
  label: string;
  value: string;
  hint?: string;
  accent?: string;
}) {
  return (
    <div className="rounded border border-border/60 bg-bg p-3">
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div
        className="mt-1 font-mono text-lg"
        style={{ color: accent ?? "#ffffff" }}
      >
        {value}
      </div>
      {hint ? <div className="mt-1 text-[11px] text-muted">{hint}</div> : null}
    </div>
  );
}

// ── Sports / leagues activas ────────────────────────────────────────────────
function SportsCard({ data }: { data: DashboardSummary }) {
  const totalActive = data.sports.filter((s) => s.leagues_detection_on > 0).length;
  const maxArbs = Math.max(1, ...data.sports.map((s) => s.arbs));
  const maxVb = Math.max(1, ...data.sports.map((s) => s.valuebets));

  return (
    <section className="rounded-lg border border-border bg-surface p-5">
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-lg font-semibold text-white">Deportes y ligas</h2>
        <span className="text-xs text-muted">
          {totalActive} de {data.sports.length} deportes con detección activa
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-[10px] uppercase tracking-wide text-muted">
            <tr className="border-b border-border">
              <th className="py-2 pr-3 text-left">Deporte</th>
              <th className="py-2 pr-3 text-left">Ligas (on / total)</th>
              <th className="py-2 pr-3 text-right">Arbs</th>
              <th className="py-2 pr-3 text-left">·</th>
              <th className="py-2 pr-3 text-right">Value bets</th>
              <th className="py-2 text-left">·</th>
            </tr>
          </thead>
          <tbody>
            {data.sports.map((s) => {
              const accent = sportAccentColor(s.sport_key, s.sport_key);
              return (
                <tr
                  key={s.sport_key}
                  className="border-b border-border/40"
                  style={{ boxShadow: `inset 4px 0 0 ${accent}` }}
                >
                  <td className="py-2 pl-2 pr-3 font-medium text-white capitalize">
                    {s.sport_name}
                  </td>
                  <td className="py-2 pr-3">
                    <span
                      className={
                        s.leagues_detection_on > 0
                          ? "font-mono text-accent"
                          : "font-mono text-muted"
                      }
                    >
                      {s.leagues_detection_on}
                    </span>
                    <span className="text-muted"> / {s.leagues_total}</span>
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-white">
                    {s.arbs}
                  </td>
                  <td className="py-2 pr-3 w-24">
                    <Bar value={s.arbs} max={maxArbs} color="#22c55e" />
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-white">
                    {s.valuebets}
                  </td>
                  <td className="py-2 w-24">
                    <Bar value={s.valuebets} max={maxVb} color="#06b6d4" />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ── Leagues panel (toggle activo/inactivo por liga) ────────────────────────
function LeaguesPanel({
  leagues,
  onToggle,
}: {
  leagues: AdminLeague[];
  onToggle: (key: string, enabled: boolean) => void | Promise<void>;
}) {
  const [search, setSearch] = useState("");
  const [openSports, setOpenSports] = useState<Set<string>>(new Set());

  const grouped = useMemo(() => {
    const q = search.trim().toLowerCase();
    const map = new Map<string, AdminLeague[]>();
    for (const lg of leagues) {
      if (
        q &&
        !lg.name.toLowerCase().includes(q) &&
        !lg.key.toLowerCase().includes(q)
      ) {
        continue;
      }
      const sport = lg.sport_key ?? "other";
      if (!map.has(sport)) map.set(sport, []);
      map.get(sport)!.push(lg);
    }
    return Array.from(map.entries())
      .map(([sport, items]) => ({
        sport,
        items: items.sort((a, b) => a.name.localeCompare(b.name)),
        on: items.filter((i) => i.detection_enabled).length,
      }))
      .sort((a, b) => a.sport.localeCompare(b.sport));
  }, [leagues, search]);

  function toggleOpen(sport: string) {
    setOpenSports((prev) => {
      const next = new Set(prev);
      if (next.has(sport)) next.delete(sport);
      else next.add(sport);
      return next;
    });
  }

  return (
    <section className="rounded-lg border border-border bg-surface p-5">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-white">Ligas — activar / desactivar</h2>
          <p className="text-xs text-muted">
            Cambia `detection_enabled`. El fetch + detección la respetan en el siguiente ciclo.
          </p>
        </div>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar liga…"
          className="rounded border border-border bg-bg px-2 py-1 text-sm text-white placeholder:text-muted"
        />
      </div>

      <div className="space-y-2">
        {grouped.map(({ sport, items, on }) => {
          const accent = sportAccentColor(sport, sport);
          const open = openSports.has(sport) || search.trim().length > 0;
          return (
            <div key={sport} className="overflow-hidden rounded border border-border">
              <button
                type="button"
                onClick={() => toggleOpen(sport)}
                className="flex w-full items-center justify-between bg-bg px-4 py-2 text-left hover:bg-white/5"
                style={{ boxShadow: `inset 4px 0 0 ${accent}` }}
              >
                <span className="text-sm font-semibold capitalize text-white">
                  {sport} <span className="font-mono text-xs text-muted">({items.length})</span>
                </span>
                <span className="text-xs text-muted">
                  <span className="font-mono text-accent">{on}</span> activas · {open ? "▾" : "▸"}
                </span>
              </button>
              {open ? (
                <ul className="divide-y divide-border/40">
                  {items.map((lg) => (
                    <li
                      key={lg.key}
                      className="flex items-center justify-between gap-4 px-4 py-2 hover:bg-white/5"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-sm text-white">{lg.name}</div>
                        <div className="truncate font-mono text-[10px] text-muted">
                          {lg.key}
                          {lg.country ? ` · ${lg.country}` : ""}
                        </div>
                      </div>
                      <Toggle
                        on={lg.detection_enabled}
                        onChange={(v) => onToggle(lg.key, v)}
                      />
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Toggle({
  on,
  onChange,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      className={`relative inline-flex h-5 w-10 shrink-0 items-center rounded-full transition ${
        on ? "bg-accent" : "bg-border"
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${
          on ? "translate-x-5" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}

// ── Top leagues ────────────────────────────────────────────────────────────
function TopLeaguesCard({ data }: { data: DashboardSummary }) {
  const max = Math.max(1, ...data.top_leagues_by_arbs.map((l) => l.arbs));
  return (
    <section className="rounded-lg border border-border bg-surface p-5">
      <h2 className="mb-1 text-lg font-semibold text-white">
        Top ligas por arbitrajes
      </h2>
      <p className="mb-4 text-xs text-muted">
        Dónde se concentran las oportunidades en la ventana
      </p>
      {data.top_leagues_by_arbs.length === 0 ? (
        <div className="text-sm text-muted">Sin arbs en la ventana.</div>
      ) : (
        <ul className="space-y-3">
          {data.top_leagues_by_arbs.map((l) => {
            const accent = sportAccentColor(l.sport_key, l.league_key);
            return (
              <li key={l.league_key}>
                <div className="mb-1 flex items-baseline justify-between text-sm">
                  <span className="text-white">{l.league_name}</span>
                  <span className="font-mono text-accent">
                    {l.arbs} <span className="text-muted">arbs</span>
                  </span>
                </div>
                <Bar value={l.arbs} max={max} color={accent} />
                <div className="mt-1 text-xs text-muted">
                  avg {l.avg_profit_pct.toFixed(2)}% · max{" "}
                  {l.max_profit_pct.toFixed(2)}%
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ── Top books ──────────────────────────────────────────────────────────────
function TopBooksCard({
  title,
  subtitle,
  items,
  accent,
}: {
  title: string;
  subtitle: string;
  items: DashboardSummary["top_books_arbs"];
  accent: string;
}) {
  const max = Math.max(1, ...items.map((b) => b.count));
  return (
    <section className="rounded-lg border border-border bg-surface p-5">
      <h2 className="mb-1 text-lg font-semibold text-white">{title}</h2>
      <p className="mb-4 text-xs text-muted">{subtitle}</p>
      {items.length === 0 ? (
        <div className="text-sm text-muted">Sin datos en la ventana.</div>
      ) : (
        <ul className="space-y-3">
          {items.map((b) => (
            <li key={b.bookmaker}>
              <div className="mb-1 flex items-baseline justify-between text-sm">
                <span className="font-mono uppercase text-white">
                  {b.bookmaker}
                </span>
                <span className="font-mono" style={{ color: accent }}>
                  {b.count}
                </span>
              </div>
              <Bar value={b.count} max={max} color={accent} />
              <div className="mt-1 text-xs text-muted">
                avg {b.avg_pct.toFixed(2)}% · max {b.max_pct.toFixed(2)}%
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── API usage ──────────────────────────────────────────────────────────────
function ApiUsageCard({ data }: { data: DashboardSummary }) {
  return (
    <section className="rounded-lg border border-border bg-surface p-5">
      <h2 className="mb-1 text-lg font-semibold text-white">Consumo de la API</h2>
      <p className="mb-4 text-xs text-muted">
        Headers `x-requests-remaining` / `x-requests-used` por fuente
      </p>
      {data.api_usage.length === 0 ? (
        <div className="text-sm text-muted">
          Aún sin lecturas. Espera al próximo fetch_odds_job (cada 5–30 min según
          smart polling).
        </div>
      ) : (
        <div className="space-y-5">
          {data.api_usage.map((u) => (
            <ApiUsageItem key={u.source} usage={u} />
          ))}
        </div>
      )}
    </section>
  );
}

function ApiUsageItem({
  usage,
}: {
  usage: DashboardSummary["api_usage"][number];
}) {
  const total =
    usage.requests_remaining != null && usage.requests_used != null
      ? usage.requests_remaining + usage.requests_used
      : null;
  const usedPct =
    total && total > 0 && usage.requests_used != null
      ? (usage.requests_used / total) * 100
      : null;

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between text-sm">
        <span className="font-mono uppercase text-white">{usage.source}</span>
        <span className="text-xs text-muted">
          {usage.calls_24h} llamadas 24h · {usage.calls_7d} en 7d
        </span>
      </div>
      {usedPct != null ? (
        <>
          <Donut percent={usedPct} />
          <div className="mt-2 flex items-baseline justify-between text-xs text-muted">
            <span>
              <span className="font-mono text-white">{usage.requests_used}</span>{" "}
              usados / {total} total
            </span>
            <span>
              <span className="font-mono text-accent">
                {usage.requests_remaining}
              </span>{" "}
              restantes
            </span>
          </div>
        </>
      ) : (
        <div className="text-xs text-muted">Sin headers de cuota disponibles.</div>
      )}
      {usage.last_captured_at ? (
        <div className="mt-2 text-xs text-muted">
          Última lectura: {usage.last_captured_at}
        </div>
      ) : null}
    </div>
  );
}

// ── Hour distribution chart (barras verticales custom) ────────────────────
function HourDistributionCard({
  title,
  subtitle,
  buckets,
  color,
}: {
  title: string;
  subtitle: string;
  buckets: HourBucket[];
  color: string;
}) {
  const max = Math.max(1, ...buckets.map((b) => b.count));
  const total = buckets.reduce((s, b) => s + b.count, 0);
  const peak = buckets.reduce((p, b) => (b.count > p.count ? b : p), buckets[0]);

  return (
    <section className="rounded-lg border border-border bg-surface p-5">
      <h2 className="mb-1 text-lg font-semibold text-white">{title}</h2>
      <p className="mb-4 text-xs text-muted">{subtitle}</p>
      {total === 0 ? (
        <div className="text-sm text-muted">Sin datos en la ventana.</div>
      ) : (
        <>
          <div className="flex items-end gap-[2px] h-32" role="img" aria-label={title}>
            {buckets.map((b) => {
              const heightPct = max > 0 ? (b.count / max) * 100 : 0;
              const isPeak = b.hour === peak.hour && b.count > 0;
              return (
                <div
                  key={b.hour}
                  className="flex-1 flex flex-col justify-end"
                  title={`${String(b.hour).padStart(2, "0")}:00 — ${b.count}`}
                >
                  <div
                    className="rounded-sm transition-all"
                    style={{
                      height: `${Math.max(heightPct, b.count > 0 ? 3 : 0)}%`,
                      backgroundColor: isPeak ? color : `${color}99`,
                      minHeight: b.count > 0 ? "2px" : "0",
                    }}
                  />
                </div>
              );
            })}
          </div>
          <div className="mt-1 flex justify-between text-[10px] text-muted font-mono">
            <span>00</span>
            <span>06</span>
            <span>12</span>
            <span>18</span>
            <span>23</span>
          </div>
          <div className="mt-3 flex justify-between text-xs text-muted">
            <span>
              Total <span className="font-mono text-white">{total}</span>
            </span>
            <span>
              Pico{" "}
              <span className="font-mono" style={{ color }}>
                {String(peak.hour).padStart(2, "0")}:00
              </span>{" "}
              ({peak.count})
            </span>
          </div>
        </>
      )}
    </section>
  );
}

// ── Primitivos de gráfico ──────────────────────────────────────────────────
function Bar({
  value,
  max,
  color,
}: {
  value: number;
  max: number;
  color: string;
}) {
  const pct = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div className="h-2 w-full overflow-hidden rounded bg-border/40">
      <div
        className="h-full rounded transition-all"
        style={{ width: `${pct}%`, backgroundColor: color }}
      />
    </div>
  );
}

function Donut({ percent }: { percent: number }) {
  const size = 110;
  const stroke = 12;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, percent));
  const dash = (clamped / 100) * c;
  const color =
    clamped < 50 ? "#22c55e" : clamped < 80 ? "#f59e0b" : "#ef4444";

  return (
    <div className="flex items-center gap-4">
      <svg width={size} height={size} className="shrink-0">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${c - dash}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        <text
          x={size / 2}
          y={size / 2 + 5}
          textAnchor="middle"
          className="fill-white text-lg font-bold"
        >
          {clamped.toFixed(0)}%
        </text>
      </svg>
      <div className="text-xs text-muted">
        Cuota mensual<br />consumida
      </div>
    </div>
  );
}
