"use client";

import Link from "next/link";

import type { Arbitrage } from "@/lib/types";
import { formatDate, formatPct, minutesUntil } from "@/lib/format";

interface Props {
  arb: Arbitrage;
  capital: number;
}

export function ArbitrageCard({ arb, capital }: Props) {
  const minutes = minutesUntil(arb.commence_time);
  const guaranteed = capital * (1 + arb.profit_pct / 100);
  const netProfit = guaranteed - capital;

  return (
    <article className="overflow-hidden rounded-lg border border-border bg-surface">
      {/* Header */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-bg px-5 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-base font-semibold text-white">
              {arb.match}
            </h3>
            <span className="rounded bg-border px-2 py-0.5 text-[10px] uppercase text-muted">
              {arb.market_type}
            </span>
          </div>
          <p className="mt-1 text-xs text-muted">
            {formatDate(arb.commence_time)}
            {arb.status === "active" && minutes > 0 ? (
              <span className="text-warn"> · en {minutes} min</span>
            ) : null}
          </p>
        </div>

        <div className="text-right">
          <div className="font-mono text-xl text-accent">
            +{formatPct(arb.profit_pct)}
          </div>
          <div className="text-xs text-muted">profit garantizado</div>
        </div>
      </header>

      {/* Legs */}
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-bg text-[10px] uppercase tracking-wide text-muted">
            <tr>
              <th className="px-5 py-2 text-left">Apostar a</th>
              <th className="px-3 py-2 text-left">Casa de apuestas</th>
              <th className="px-3 py-2 text-right">Cuota</th>
              <th className="px-3 py-2 text-right">% stake</th>
              <th className="px-3 py-2 text-right">€ a apostar</th>
              <th className="px-5 py-2 text-right">€ a cobrar</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {arb.legs.map((leg) => {
              const stake = capital * leg.stake_pct;
              const payout = stake * leg.odds;
              return (
                <tr key={`${arb.id}-${leg.outcome}-${leg.bookmaker}`}>
                  <td className="px-5 py-2 font-medium text-white">
                    {leg.outcome_name}
                  </td>
                  <td className="px-3 py-2 uppercase text-muted">
                    {leg.bookmaker}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">
                    {leg.odds.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-muted">
                    {(leg.stake_pct * 100).toFixed(2)}%
                  </td>
                  <td className="px-3 py-2 text-right font-mono">
                    € {stake.toFixed(2)}
                  </td>
                  <td className="px-5 py-2 text-right font-mono text-accent">
                    € {payout.toFixed(2)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-bg px-5 py-3 text-sm">
        <div className="text-muted">
          Invirtiendo <span className="font-mono text-white">€ {capital.toFixed(2)}</span>{" "}
          cobras{" "}
          <span className="font-mono text-accent">€ {guaranteed.toFixed(2)}</span> (beneficio
          neto <span className="font-mono text-accent">€ {netProfit.toFixed(2)}</span>)
        </div>
        <Link
          href={`/arbitrage/${arb.id}`}
          className="text-accent hover:text-accentHover"
        >
          Detalle →
        </Link>
      </footer>
    </article>
  );
}
