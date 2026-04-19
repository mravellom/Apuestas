"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ExecutionPanel } from "@/components/ExecutionPanel";
import { Header } from "@/components/Header";
import { StakeCalculator } from "@/components/StakeCalculator";
import { getArbitrage } from "@/lib/api";
import { isAuthenticated } from "@/lib/auth";
import { formatDate, formatPct, minutesUntil } from "@/lib/format";
import type { Arbitrage } from "@/lib/types";

interface Props {
  params: Promise<{ id: string }>;
}

export default function ArbitrageDetailPage({ params }: Props) {
  const { id } = use(params);
  const arbId = Number(id);
  const router = useRouter();
  const [arb, setArb] = useState<Arbitrage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await getArbitrage(arbId);
        if (!cancelled) setArb(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Error cargando oportunidad");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [arbId, router]);

  return (
    <div className="min-h-screen">
      <Header />

      <main className="mx-auto max-w-5xl px-6 py-8">
        <Link
          href="/arbitrage"
          className="mb-4 inline-block text-sm text-muted hover:text-accent"
        >
          ← Volver a la lista
        </Link>

        {loading ? (
          <p className="text-muted">Cargando…</p>
        ) : error ? (
          <p className="text-danger">{error}</p>
        ) : !arb ? (
          <p className="text-muted">Oportunidad no encontrada o ya expirada.</p>
        ) : (
          <>
            <header className="mb-6">
              <div className="flex items-baseline justify-between gap-4">
                <h1 className="text-2xl font-bold text-white">{arb.match}</h1>
                <span
                  className={`rounded px-2 py-1 text-xs uppercase ${
                    arb.status === "active"
                      ? "bg-accent/10 text-accent"
                      : "bg-border text-muted"
                  }`}
                >
                  {arb.status}
                </span>
              </div>
              <div className="mt-2 text-sm text-muted">
                <span className="uppercase">{arb.market_type}</span> ·{" "}
                {formatDate(arb.commence_time)}
                {arb.status === "active" && minutesUntil(arb.commence_time) > 0 ? (
                  <span className="text-warn">
                    {" · en "}
                    {minutesUntil(arb.commence_time)} min
                  </span>
                ) : null}
              </div>
            </header>

            <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Metric
                label="Profit garantizado"
                value={`+${formatPct(arb.profit_pct)}`}
                highlight
              />
              <Metric
                label="Σ prob. implícita"
                value={arb.total_implied.toFixed(4)}
              />
              <Metric label="Nº outcomes" value={String(arb.legs.length)} />
            </div>

            <div className="mb-6">
              <StakeCalculator legs={arb.legs} profitPct={arb.profit_pct} />
            </div>

            {arb.status === "active" ? <ExecutionPanel arb={arb} /> : null}
          </>
        )}
      </main>
    </div>
  );
}

function Metric({
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
