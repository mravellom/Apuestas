"use client";

import { formatMoney } from "@/lib/format";
import type { ExposureSummary } from "@/lib/types";

/**
 * Muestra la exposición real del usuario sobre un arb dado su estado de legs.
 * Es el contrapeso al StakeCalculator teórico: acá ves qué pasa SI uno o más
 * legs fallaron. Si hay partial fill, sugiere libros alternativos.
 */
export function ExposurePanel({ exposure }: { exposure: ExposureSummary }) {
  if (exposure.legs.length === 0) return null;

  const { currency } = exposure;

  return (
    <div className="mt-6 rounded-lg border border-border bg-surface p-6">
      <header className="mb-4 flex items-baseline justify-between">
        <h2 className="text-lg font-semibold text-white">Exposición real</h2>
        <StatusTag exposure={exposure} />
      </header>

      {exposure.is_partial_fill ? (
        <div className="mb-4 rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          ⚠ <strong>Partial fill detectado.</strong> Tienes legs placed sin
          cobertura completa. Evalúa los escenarios debajo y considera cubrir los
          legs rechazados con otro libro.
        </div>
      ) : null}

      <div className="mb-4 grid grid-cols-3 gap-3 text-sm">
        <Stat label="Stake colocado">
          <span className="font-mono text-white">
            {formatMoney(exposure.total_placed_stake, currency)}
          </span>
        </Stat>
        <Stat label="Peor escenario">
          <span
            className={`font-mono ${
              exposure.worst_case_pnl >= 0 ? "text-accent" : "text-danger"
            }`}
          >
            {exposure.worst_case_pnl >= 0 ? "+" : ""}
            {formatMoney(exposure.worst_case_pnl, currency)}
          </span>
        </Stat>
        <Stat label="Mejor escenario">
          <span
            className={`font-mono ${
              exposure.best_case_pnl >= 0 ? "text-accent" : "text-danger"
            }`}
          >
            {exposure.best_case_pnl >= 0 ? "+" : ""}
            {formatMoney(exposure.best_case_pnl, currency)}
          </span>
        </Stat>
      </div>

      <table className="mb-4 min-w-full divide-y divide-border text-sm">
        <thead className="bg-bg text-xs uppercase tracking-wide text-muted">
          <tr>
            <th className="px-3 py-2 text-left">Si gana…</th>
            <th className="px-3 py-2 text-left">Cubierto</th>
            <th className="px-3 py-2 text-right">P&amp;L</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {exposure.scenarios.map((s) => (
            <tr key={s.outcome_key}>
              <td className="px-3 py-2 text-white">{s.outcome_name}</td>
              <td className="px-3 py-2">
                {s.covered ? (
                  <span className="text-accent">Sí</span>
                ) : (
                  <span className="text-danger">No</span>
                )}
              </td>
              <td
                className={`px-3 py-2 text-right font-mono ${
                  s.pnl > 0
                    ? "text-accent"
                    : s.pnl < 0
                      ? "text-danger"
                      : "text-muted"
                }`}
              >
                {s.pnl >= 0 ? "+" : ""}
                {formatMoney(s.pnl, currency)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {exposure.replacement_suggestions.length > 0 ? (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-white">
            Libros alternativos para cubrir rechazos
          </h3>
          <div className="space-y-3">
            {exposure.replacement_suggestions.map((sug) => (
              <div
                key={`${sug.outcome_key}-${sug.rejected_bookmaker_key}`}
                className="rounded border border-border bg-bg/50 p-3"
              >
                <div className="mb-2 text-sm">
                  <span className="text-muted">Para cubrir </span>
                  <span className="font-semibold text-white">
                    {sug.outcome_name}
                  </span>{" "}
                  <span className="text-muted">
                    (rechazado por{" "}
                    <code className="text-xs">{sug.rejected_bookmaker_key}</code>
                    )
                  </span>
                </div>
                {sug.alternatives.length === 0 ? (
                  <p className="text-xs text-muted">
                    Sin alternativas con cuotas recientes en otros libros.
                  </p>
                ) : (
                  <ul className="space-y-1 text-sm">
                    {sug.alternatives.map((alt) => (
                      <li
                        key={alt.bookmaker_key}
                        className="flex items-center justify-between font-mono"
                      >
                        <span className="text-white">{alt.bookmaker_name}</span>
                        <span className="text-accent">
                          {alt.odds.toFixed(2)}
                        </span>
                        {alt.commission_pct > 0 ? (
                          <span className="text-xs text-muted">
                            comisión {(alt.commission_pct * 100).toFixed(2)}%
                          </span>
                        ) : (
                          <span className="text-xs text-muted">sin comisión</span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted">
            La cobertura manual es responsabilidad del usuario: apuesta en uno de
            estos libros y luego marca ese leg rechazado como{" "}
            <em>&quot;placed&quot;</em> en{" "}
            <a href="/bets" className="underline">
              /bets
            </a>{" "}
            con la cuota que hayas obtenido.
          </p>
        </div>
      ) : null}
    </div>
  );
}

function StatusTag({ exposure }: { exposure: ExposureSummary }) {
  if (exposure.is_partial_fill) {
    return (
      <span className="rounded bg-danger/20 px-2 py-0.5 text-xs uppercase text-danger">
        Exposición unilateral
      </span>
    );
  }
  if (exposure.all_placed) {
    return (
      <span className="rounded bg-accent/20 px-2 py-0.5 text-xs uppercase text-accent">
        Cubierto
      </span>
    );
  }
  return (
    <span className="rounded bg-warn/20 px-2 py-0.5 text-xs uppercase text-warn">
      Parcial pending
    </span>
  );
}

function Stat({
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
