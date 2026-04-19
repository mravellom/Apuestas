"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Header } from "@/components/Header";
import { getDailyPlan, listBankrolls } from "@/lib/api";
import { isAuthenticated } from "@/lib/auth";
import { formatMoney } from "@/lib/format";
import type { Bankroll, DailyPlan } from "@/lib/types";

export default function PlanningPage() {
  const router = useRouter();
  const [bankrolls, setBankrolls] = useState<Bankroll[]>([]);
  const [bankrollId, setBankrollId] = useState<number | null>(null);
  const [dailyCap, setDailyCap] = useState<number>(500);
  const [targetPct, setTargetPct] = useState<number>(1.0);
  const [maxPerArbPct, setMaxPerArbPct] = useState<number>(15);
  const [plan, setPlan] = useState<DailyPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    (async () => {
      try {
        const brs = await listBankrolls();
        setBankrolls(brs);
        if (brs.length > 0) {
          setBankrollId(brs[0].id);
          setDailyCap(Math.min(brs[0].available_amount, 500));
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error cargando bankrolls");
      }
    })();
  }, [router]);

  async function compute() {
    if (bankrollId === null) {
      setError("Selecciona un bankroll");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const p = await getDailyPlan({
        bankrollId,
        dailyCap,
        targetPct,
        maxStakePerArbPct: maxPerArbPct,
      });
      setPlan(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error calculando plan");
    } finally {
      setLoading(false);
    }
  }

  const selectedBankroll = bankrolls.find((b) => b.id === bankrollId) ?? null;

  return (
    <div className="min-h-screen">
      <Header />
      <main className="mx-auto max-w-6xl px-6 py-8">
        <h1 className="mb-2 text-2xl font-bold text-white">
          Planificador diario
        </h1>
        <p className="mb-6 text-sm text-muted">
          Define cuánto quieres invertir hoy y qué % de profit buscas. El
          sistema ordena los arbs activos por rentabilidad y te sugiere el
          stake óptimo por cada uno para cubrir el target sin exceder el tope.
        </p>

        {error ? (
          <p className="mb-4 rounded border border-danger/40 bg-danger/10 p-2 text-sm text-danger">
            {error}
          </p>
        ) : null}

        <section className="mb-6 rounded-lg border border-border bg-surface p-6">
          <h2 className="mb-4 text-lg font-semibold text-white">Parámetros</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
            <div>
              <label className="block text-xs uppercase tracking-wide text-muted">
                Bankroll
              </label>
              <select
                value={bankrollId ?? ""}
                onChange={(e) => setBankrollId(Number(e.target.value))}
                className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 text-sm text-white"
              >
                {bankrolls.length === 0 ? (
                  <option value="">—</option>
                ) : null}
                {bankrolls.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name} ({b.currency}) — disp{" "}
                    {formatMoney(b.available_amount, b.currency)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wide text-muted">
                Tope de inversión hoy{" "}
                {selectedBankroll ? `(${selectedBankroll.currency})` : ""}
              </label>
              <input
                type="number"
                min="1"
                step="50"
                value={dailyCap}
                onChange={(e) =>
                  setDailyCap(Math.max(1, Number(e.target.value) || 0))
                }
                className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wide text-muted">
                Target profit (%)
              </label>
              <input
                type="number"
                min="0.1"
                max="100"
                step="0.1"
                value={targetPct}
                onChange={(e) =>
                  setTargetPct(Math.max(0.1, Number(e.target.value) || 0))
                }
                className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wide text-muted">
                Max stake / arb (%)
              </label>
              <input
                type="number"
                min="1"
                max="100"
                step="1"
                value={maxPerArbPct}
                onChange={(e) =>
                  setMaxPerArbPct(Math.max(1, Number(e.target.value) || 0))
                }
                className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 text-sm text-white"
              />
            </div>
          </div>
          <div className="mt-4">
            <button
              onClick={compute}
              disabled={loading || bankrollId === null}
              className="rounded bg-accent px-4 py-2 text-sm font-semibold text-bg disabled:opacity-50"
            >
              {loading ? "Calculando…" : "Calcular plan"}
            </button>
          </div>
        </section>

        {plan ? <PlanResult plan={plan} bankrollId={bankrollId!} /> : null}
      </main>
    </div>
  );
}

function PlanResult({
  plan,
  bankrollId,
}: {
  plan: DailyPlan;
  bankrollId: number;
}) {
  const statusStyles: Record<string, string> = {
    achievable: "border-accent/40 bg-accent/10 text-accent",
    exceeded: "border-accent/40 bg-accent/10 text-accent",
    unachievable: "border-warn/40 bg-warn/10 text-warn",
    empty: "border-border bg-bg/50 text-muted",
  };

  return (
    <section className="rounded-lg border border-border bg-surface p-6">
      <header className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white">Plan sugerido</h2>
          <p className="text-xs text-muted">
            {plan.available_arbs} arb(s) activos disponibles
          </p>
        </div>
        <span
          className={`rounded border px-3 py-1 text-xs uppercase ${
            statusStyles[plan.status] ?? "border-border bg-bg/50 text-muted"
          }`}
        >
          {plan.status}
        </span>
      </header>

      <div className="mb-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <Metric label="Target">
          <span className="font-mono text-white">
            {formatMoney(plan.target_profit, plan.currency)}
          </span>
          <span className="ml-1 text-xs text-muted">
            ({plan.target_pct.toFixed(2)}%)
          </span>
        </Metric>
        <Metric label="Profit esperado">
          <span className="font-mono text-accent">
            {formatMoney(plan.expected_total_profit, plan.currency)}
          </span>
        </Metric>
        <Metric label="Capital asignado">
          <span className="font-mono text-white">
            {formatMoney(plan.total_suggested_stake, plan.currency)}
          </span>
          <span className="ml-1 text-xs text-muted">
            / {formatMoney(plan.daily_investment_cap, plan.currency)}
          </span>
        </Metric>
        <Metric label="Coverage">
          <span className="font-mono text-white">
            {plan.target_coverage_pct.toFixed(1)}%
          </span>
        </Metric>
      </div>

      <CoverageBar coverage={plan.target_coverage_pct} />

      <p className="mt-4 mb-4 rounded border border-border bg-bg/50 p-3 text-sm">
        {plan.recommendation}
      </p>

      {plan.allocations.length === 0 ? (
        <p className="text-sm text-muted">
          Sin allocations. Ajusta parámetros o espera a nuevos arbs.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-border text-sm">
            <thead className="bg-bg text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-3 py-2 text-left">#</th>
                <th className="px-3 py-2 text-left">Partido</th>
                <th className="px-3 py-2 text-left">Mercado</th>
                <th className="px-3 py-2 text-left">Books</th>
                <th className="px-3 py-2 text-right">Profit %</th>
                <th className="px-3 py-2 text-right">Stake</th>
                <th className="px-3 py-2 text-right">Profit esp.</th>
                <th className="px-3 py-2 text-right">Acción</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {plan.allocations.map((a, idx) => (
                <tr key={a.arbitrage_id}>
                  <td className="px-3 py-2 text-muted">{idx + 1}</td>
                  <td className="px-3 py-2 text-white">{a.match_label}</td>
                  <td className="px-3 py-2 uppercase text-muted">
                    {a.market_type}
                  </td>
                  <td className="px-3 py-2 text-xs text-muted">
                    {a.bookmakers.join(", ")}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-accent">
                    {a.profit_pct.toFixed(2)}%
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-white">
                    {formatMoney(a.suggested_stake, plan.currency)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-accent">
                    +{formatMoney(a.expected_profit, plan.currency)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Link
                      href={`/arbitrage/${a.arbitrage_id}?stake=${a.suggested_stake}&bankroll=${bankrollId}`}
                      className="rounded bg-accent px-3 py-1 text-xs font-medium text-bg"
                    >
                      Ejecutar
                    </Link>
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

function CoverageBar({ coverage }: { coverage: number }) {
  const clamped = Math.min(100, Math.max(0, coverage));
  const color =
    clamped >= 100 ? "bg-accent" : clamped >= 60 ? "bg-warn" : "bg-danger";
  return (
    <div className="h-2 overflow-hidden rounded bg-bg">
      <div
        className={`h-full ${color} transition-all`}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

function Metric({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded border border-border bg-bg/50 p-3">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1">{children}</div>
    </div>
  );
}
