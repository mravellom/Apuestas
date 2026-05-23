"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { ArbitrageCard } from "@/components/ArbitrageCard";
import { FilterBar } from "@/components/FilterBar";
import { Header } from "@/components/Header";
import { listArbitrage } from "@/lib/api";
import { isAuthenticated } from "@/lib/auth";
import { useOpportunityStream } from "@/lib/eventStream";
import type { Arbitrage } from "@/lib/types";

type Status = "active" | "expired";

export default function ArbitrageListPage() {
  const router = useRouter();
  const [items, setItems] = useState<Arbitrage[]>([]);
  const [status, setStatus] = useState<Status>("active");
  const [minProfit, setMinProfit] = useState(0.5);
  const [capital, setCapital] = useState(100);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listArbitrage({ status, minProfit });
      setItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error cargando oportunidades");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [status, minProfit]);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    void load();
  }, [load, router]);

  // Auto-refresh cada 60 segundos como fallback si SSE cae
  useEffect(() => {
    const id = window.setInterval(() => {
      if (isAuthenticated()) void load();
    }, 60_000);
    return () => window.clearInterval(id);
  }, [load]);

  // SSE: refetch inmediato cuando llega evento de arb nueva (perceptibilidad ~1s vs 60s)
  useOpportunityStream({
    onArbitrage: useCallback(() => {
      if (isAuthenticated()) void load();
    }, [load]),
  });

  const stats = useMemo(() => {
    if (items.length === 0) return null;
    const best = Math.max(...items.map((a) => a.profit_pct));
    const avg =
      items.reduce((sum, a) => sum + a.profit_pct, 0) / items.length;
    const totalNet = items.reduce(
      (sum, a) => sum + capital * (a.profit_pct / 100),
      0,
    );
    return { count: items.length, best, avg, totalNet };
  }, [items, capital]);

  return (
    <div className="min-h-screen">
      <Header />

      <main className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-white">Oportunidades de arbitraje</h1>
          <p className="mt-1 text-sm text-muted">
            Combinaciones con ganancia matemática garantizada. Cada tarjeta muestra en
            qué casa apostar y cuánto apostar en cada outcome según el capital configurado.
          </p>
        </div>

        {stats ? (
          <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Activas" value={`${stats.count}`} />
            <StatCard
              label="Mejor profit"
              value={`+${stats.best.toFixed(2)}%`}
              highlight
            />
            <StatCard label="Profit medio" value={`+${stats.avg.toFixed(2)}%`} />
            <StatCard
              label={`Beneficio con ${capital}/arb`}
              value={stats.totalNet.toFixed(2)}
              highlight
            />
          </div>
        ) : null}

        <div className="mb-6">
          <FilterBar
            status={status}
            minProfit={minProfit}
            capital={capital}
            onChange={({ status: s, minProfit: m, capital: c }) => {
              setStatus(s);
              setMinProfit(m);
              setCapital(c);
            }}
            onRefresh={() => void load()}
            loading={loading}
          />
        </div>

        {error ? (
          <div className="mb-4 rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        {items.length === 0 && !loading ? (
          <div className="rounded-lg border border-border bg-surface p-8 text-center text-muted">
            No hay oportunidades con los filtros seleccionados.
          </div>
        ) : (
          <div className="space-y-4">
            {items.map((arb) => (
              <ArbitrageCard key={arb.id} arb={arb} capital={capital} />
            ))}
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
