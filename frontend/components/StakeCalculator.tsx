"use client";

import { useMemo, useState } from "react";

import type { ArbitrageLeg } from "@/lib/types";

interface Props {
  legs: ArbitrageLeg[];
  profitPct: number;
}

export function StakeCalculator({ legs, profitPct }: Props) {
  const [capital, setCapital] = useState(100);

  const rows = useMemo(
    () =>
      legs.map((leg) => {
        const stake = capital * leg.stake_pct;
        const payout = stake * leg.odds;
        return { ...leg, stake, payout };
      }),
    [legs, capital],
  );

  const totalStake = rows.reduce((sum, r) => sum + r.stake, 0);
  const guaranteedPayout = capital * (1 + profitPct / 100);
  const netProfit = guaranteedPayout - totalStake;

  return (
    <div className="rounded-lg border border-border bg-surface p-6">
      <div className="mb-4 flex items-end gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-xs uppercase tracking-wide text-muted">
            Capital a invertir (€)
          </label>
          <input
            type="number"
            min="1"
            step="10"
            value={capital}
            onChange={(e) => setCapital(Math.max(1, Number(e.target.value) || 0))}
            className="w-40 rounded border border-border bg-bg px-3 py-2 text-sm text-white"
          />
        </div>
        <div className="ml-auto text-right text-sm">
          <div className="text-muted">Payout garantizado</div>
          <div className="font-mono text-lg text-accent">
            € {guaranteedPayout.toFixed(2)}
          </div>
          <div className="text-xs text-muted">
            Beneficio neto:{" "}
            <span className="text-accent">€ {netProfit.toFixed(2)}</span>
          </div>
        </div>
      </div>

      <table className="min-w-full divide-y divide-border text-sm">
        <thead className="bg-bg text-xs uppercase tracking-wide text-muted">
          <tr>
            <th className="px-3 py-2 text-left">Outcome</th>
            <th className="px-3 py-2 text-left">Bookmaker</th>
            <th className="px-3 py-2 text-right">Cuota</th>
            <th className="px-3 py-2 text-right">% stake</th>
            <th className="px-3 py-2 text-right">€ stake</th>
            <th className="px-3 py-2 text-right">€ payout</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row) => (
            <tr key={`${row.outcome}-${row.bookmaker}`}>
              <td className="px-3 py-2 text-white">{row.outcome_name}</td>
              <td className="px-3 py-2 uppercase text-muted">{row.bookmaker}</td>
              <td className="px-3 py-2 text-right font-mono">{row.odds.toFixed(2)}</td>
              <td className="px-3 py-2 text-right font-mono text-muted">
                {(row.stake_pct * 100).toFixed(2)}%
              </td>
              <td className="px-3 py-2 text-right font-mono">
                € {row.stake.toFixed(2)}
              </td>
              <td className="px-3 py-2 text-right font-mono text-accent">
                € {row.payout.toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="mt-4 text-xs text-muted">
        Los stakes están calibrados para que <strong>cualquier outcome</strong> rinda el
        mismo payout garantizado. El beneficio neto es independiente del resultado del
        partido.
      </p>
    </div>
  );
}
