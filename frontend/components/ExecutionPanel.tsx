"use client";

import { useEffect, useMemo, useState } from "react";

import {
  executeArbitrage,
  getArbitrageExposure,
  listBankrolls,
  listBets,
  placeBet,
  rejectBet,
  revalidateArbitrage,
} from "@/lib/api";
import { formatMoney } from "@/lib/format";
import type {
  Arbitrage,
  Bankroll,
  Bet,
  ExecutionPlan,
  ExposureSummary,
  LegInstruction,
  RevalidationResult,
} from "@/lib/types";
import { ExposurePanel } from "@/components/ExposurePanel";

interface Props {
  arb: Arbitrage;
  /**
   * Stake y bankroll sugeridos por el planificador. Si vienen, se prellenan
   * los campos y se expande el flow directo a ejecutar.
   */
  prefillStake?: number;
  prefillBankrollId?: number;
}

/**
 * Flujo:
 *   1. Usuario elige bankroll y stake total.
 *   2. "Ejecutar" → backend crea N bets en pending + reserva capital.
 *   3. Por cada leg, usuario abre el libro manualmente, apuesta, vuelve,
 *      ingresa la cuota real conseguida y marca como placed (o rechaza si
 *      la cuota cayó fuera de tolerancia).
 *   4. Tras resultado del partido, liquidación en /bets.
 */
export function ExecutionPanel({ arb, prefillStake, prefillBankrollId }: Props) {
  const [bankrolls, setBankrolls] = useState<Bankroll[] | null>(null);
  const [bankrollId, setBankrollId] = useState<number | null>(
    prefillBankrollId ?? null,
  );
  const [totalStake, setTotalStake] = useState(prefillStake ?? 500);
  const [plan, setPlan] = useState<ExecutionPlan | null>(null);
  const [bets, setBets] = useState<Record<number, Bet>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revalidation, setRevalidation] = useState<RevalidationResult | null>(null);
  const [revalidating, setRevalidating] = useState(false);
  const [exposure, setExposure] = useState<ExposureSummary | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const brs = await listBankrolls();
        setBankrolls(brs);
        // Si no vino prefillBankrollId, elige el primero.
        if (brs.length > 0 && bankrollId === null) setBankrollId(brs[0].id);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error cargando bankrolls");
      }
    })();
    // bankrollId intentionally omitted — solo queremos correr al montar.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function doRevalidate() {
    setRevalidating(true);
    setError(null);
    try {
      const r = await revalidateArbitrage(arb.id);
      setRevalidation(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error revalidando");
    } finally {
      setRevalidating(false);
    }
  }

  const selectedBankroll = bankrolls?.find((b) => b.id === bankrollId) ?? null;

  const maxStake = selectedBankroll?.available_amount ?? 0;

  async function handleExecute(forceIfStale = false) {
    if (!bankrollId) {
      setError("Necesitas crear un bankroll primero");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const p = await executeArbitrage(arb.id, bankrollId, totalStake, forceIfStale);
      setPlan(p);
      const [currentBets, exp] = await Promise.all([
        listBets({ arbitrageId: arb.id }),
        getArbitrageExposure(arb.id),
      ]);
      const byId: Record<number, Bet> = {};
      for (const b of currentBets) byId[b.id] = b;
      setBets(byId);
      setExposure(exp);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error ejecutando");
    } finally {
      setLoading(false);
    }
  }

  async function refreshBet(_betId: number) {
    try {
      const [all, exp] = await Promise.all([
        listBets({ arbitrageId: arb.id }),
        getArbitrageExposure(arb.id),
      ]);
      const byId: Record<number, Bet> = {};
      for (const b of all) byId[b.id] = b;
      setBets(byId);
      setExposure(exp);
    } catch {
      /* non-fatal */
    }
  }

  if (bankrolls === null) {
    return (
      <div className="rounded-lg border border-border bg-surface p-6">
        <p className="text-muted">Cargando bankrolls…</p>
      </div>
    );
  }

  if (bankrolls.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-surface p-6">
        <h2 className="mb-2 text-lg font-semibold text-white">Ejecutar arbitraje</h2>
        <p className="mb-3 text-sm text-muted">
          Necesitas al menos un bankroll configurado para ejecutar arbitrajes con
          tracking real.
        </p>
        <a
          href="/bankroll"
          className="inline-block rounded bg-accent px-4 py-2 text-sm font-medium text-bg"
        >
          Crear bankroll →
        </a>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-surface p-6">
      <h2 className="mb-4 text-lg font-semibold text-white">
        Ejecutar arbitraje
      </h2>

      {error ? (
        <p className="mb-3 rounded border border-danger/40 bg-danger/10 p-2 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {!plan ? (
        <div className="space-y-4">
          <RevalidationBanner
            revalidation={revalidation}
            loading={revalidating}
            onCheck={doRevalidate}
          />

          <div>
            <label className="block text-xs uppercase tracking-wide text-muted">
              Bankroll
            </label>
            <select
              value={bankrollId ?? ""}
              onChange={(e) => setBankrollId(Number(e.target.value))}
              className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 text-sm text-white"
            >
              {bankrolls.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} — disponible {formatMoney(b.available_amount, b.currency)}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wide text-muted">
              Capital total ({selectedBankroll?.currency ?? ""})
            </label>
            <input
              type="number"
              min="1"
              step="10"
              max={maxStake}
              value={totalStake}
              onChange={(e) =>
                setTotalStake(Math.max(1, Number(e.target.value) || 0))
              }
              className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 text-sm text-white"
            />
            <p className="mt-1 text-xs text-muted">
              Máximo disponible:{" "}
              {selectedBankroll
                ? formatMoney(maxStake, selectedBankroll.currency)
                : maxStake.toFixed(2)}
            </p>
          </div>

          <button
            disabled={loading || !bankrollId || totalStake > maxStake}
            onClick={() => handleExecute(revalidation?.status === "stale")}
            className="w-full rounded bg-accent px-4 py-2 text-sm font-semibold text-bg disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading
              ? "Reservando capital…"
              : revalidation?.status === "stale"
                ? "Ejecutar igualmente (forzar stale)"
                : "Ejecutar (crea apuestas pending)"}
          </button>

          <p className="text-xs text-muted">
            El sistema creará {arb.legs.length} apuestas en status{" "}
            <code>pending</code> y reservará el capital en el bankroll. Tendrás
            que apostar manualmente en cada libro y luego volver aquí para
            confirmar la cuota real conseguida.
          </p>
        </div>
      ) : (
        <>
          <ExecutionProgress plan={plan} bets={bets} onChanged={() => refreshBet(0)} />
          {exposure ? <ExposurePanel exposure={exposure} /> : null}
        </>
      )}
    </div>
  );
}

function ExecutionProgress({
  plan,
  bets,
  onChanged,
}: {
  plan: ExecutionPlan;
  bets: Record<number, Bet>;
  onChanged: () => void;
}) {
  const allPlaced = plan.legs.every((leg) => {
    const b = bets[leg.bet_id];
    return b && (b.status === "placed" || b.status === "confirmed");
  });

  const anyRejected = plan.legs.some(
    (leg) => bets[leg.bet_id]?.status === "rejected",
  );

  return (
    <div className="space-y-4">
      <div className="rounded border border-border bg-bg/50 p-3 text-sm">
        <div className="flex justify-between">
          <span className="text-muted">Stake total</span>
          <span className="font-mono text-white">
            {formatMoney(plan.total_stake, plan.currency)}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted">Profit esperado</span>
          <span className="font-mono text-accent">
            +{formatMoney(plan.expected_profit, plan.currency)} (
            {plan.profit_pct.toFixed(2)}%)
          </span>
        </div>
      </div>

      {anyRejected ? (
        <div className="rounded border border-warn/40 bg-warn/10 p-3 text-sm text-warn">
          ⚠️ Uno o más legs fueron rechazados. Si otros ya están colocados, tienes
          exposición unilateral — considera rebalancear manualmente o marcar los
          placed como rejected para cancelar el arb.
        </div>
      ) : null}

      {allPlaced ? (
        <div className="rounded border border-accent/40 bg-accent/10 p-3 text-sm text-accent">
          ✓ Arbitraje completo. Al liquidarse el partido, marca cada leg como
          ganado/perdido en{" "}
          <a href="/bets" className="underline">
            /bets
          </a>
          .
        </div>
      ) : null}

      <div className="space-y-3">
        {plan.legs.map((leg) => (
          <LegCard
            key={leg.bet_id}
            leg={leg}
            currency={plan.currency}
            bet={bets[leg.bet_id] ?? null}
            onChanged={onChanged}
          />
        ))}
      </div>
    </div>
  );
}

function LegCard({
  leg,
  currency,
  bet,
  onChanged,
}: {
  leg: LegInstruction;
  currency: string;
  bet: Bet | null;
  onChanged: () => void;
}) {
  const [placedOdds, setPlacedOdds] = useState<string>(leg.target_odds.toFixed(2));
  const [working, setWorking] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const status = bet?.status ?? "pending";

  async function handlePlace() {
    const odds = Number(placedOdds);
    if (!Number.isFinite(odds) || odds <= 1) {
      setErr("Cuota inválida");
      return;
    }
    setWorking(true);
    setErr(null);
    try {
      await placeBet(leg.bet_id, odds);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error marcando placed");
    } finally {
      setWorking(false);
    }
  }

  async function handleReject() {
    setWorking(true);
    setErr(null);
    try {
      await rejectBet(leg.bet_id);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error rechazando");
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="rounded border border-border bg-bg/50 p-4">
      <div className="mb-2 flex items-baseline justify-between">
        <div>
          <span className="text-xs uppercase tracking-wide text-muted">
            {leg.bookmaker_name}
          </span>
          <h3 className="text-base font-semibold text-white">{leg.outcome_name}</h3>
        </div>
        <StatusBadge status={status} />
      </div>

      <div className="grid grid-cols-3 gap-3 text-sm">
        <Field label="Stake">
          <span className="font-mono text-white">
            {formatMoney(leg.stake_amount, currency)}
          </span>
        </Field>
        <Field label="Cuota objetivo">
          <span className="font-mono text-white">
            {leg.target_odds.toFixed(2)}
          </span>
        </Field>
        <Field label="Mín. aceptable">
          <span className="font-mono text-muted">
            {leg.min_acceptable_odds.toFixed(2)}
          </span>
        </Field>
      </div>

      {leg.commission_pct > 0 ? (
        <p className="mt-2 text-xs text-muted">
          Comisión aplicada: {(leg.commission_pct * 100).toFixed(2)}%
        </p>
      ) : null}

      {err ? <p className="mt-2 text-sm text-danger">{err}</p> : null}

      {status === "pending" ? (
        <div className="mt-3 flex items-end gap-2">
          <div className="flex-1">
            <label className="block text-xs uppercase tracking-wide text-muted">
              Cuota real conseguida
            </label>
            <input
              type="number"
              step="0.01"
              min="1.01"
              value={placedOdds}
              onChange={(e) => setPlacedOdds(e.target.value)}
              className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 text-sm text-white"
            />
          </div>
          <button
            onClick={handlePlace}
            disabled={working}
            className="rounded bg-accent px-3 py-2 text-sm font-medium text-bg disabled:opacity-50"
          >
            Marcar colocada
          </button>
          <button
            onClick={handleReject}
            disabled={working}
            className="rounded border border-border px-3 py-2 text-sm text-muted hover:border-danger hover:text-danger disabled:opacity-50"
          >
            Rechazar
          </button>
        </div>
      ) : null}

      {status === "placed" && bet?.odds_at_placement ? (
        <p className="mt-2 text-xs text-muted">
          Colocada a cuota {bet.odds_at_placement.toFixed(2)}
          {bet.odds_at_detection && bet.odds_at_detection !== bet.odds_at_placement
            ? ` (detectada ${bet.odds_at_detection.toFixed(2)})`
            : ""}
        </p>
      ) : null}
    </div>
  );
}

function RevalidationBanner({
  revalidation,
  loading,
  onCheck,
}: {
  revalidation: RevalidationResult | null;
  loading: boolean;
  onCheck: () => void;
}) {
  if (!revalidation) {
    return (
      <div className="rounded border border-border bg-bg/50 p-3 text-sm">
        <div className="flex items-center justify-between gap-3">
          <span className="text-muted">
            Verifica si el arb sigue activo con las cuotas más recientes antes
            de ejecutar.
          </span>
          <button
            onClick={onCheck}
            disabled={loading}
            className="rounded bg-accent/10 px-3 py-1 text-xs font-medium text-accent disabled:opacity-50"
          >
            {loading ? "Revalidando…" : "Revalidar ahora"}
          </button>
        </div>
      </div>
    );
  }

  const colorByStatus: Record<string, string> = {
    alive: "border-accent/40 bg-accent/10 text-accent",
    stale: "border-warn/40 bg-warn/10 text-warn",
    dead: "border-danger/40 bg-danger/10 text-danger",
  };
  const labelByStatus: Record<string, string> = {
    alive: "✓ Vivo",
    stale: "⚠ Degradado",
    dead: "✗ Muerto",
  };

  return (
    <div
      className={`rounded border p-3 text-sm ${
        colorByStatus[revalidation.status] ?? "border-border bg-bg/50 text-muted"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold">
            {labelByStatus[revalidation.status] ?? revalidation.status}
          </div>
          <div className="mt-1 text-xs">
            Profit actual:{" "}
            <span className="font-mono">
              {revalidation.current_profit_pct.toFixed(2)}%
            </span>{" "}
            (detectado {revalidation.detected_profit_pct.toFixed(2)}%) · Edad{" "}
            {Math.round(revalidation.age_seconds / 60)} min
          </div>
          {revalidation.status === "stale" ? (
            <div className="mt-1 text-xs">
              Las cuotas bajaron. Puedes seguir, pero el beneficio real será
              menor al detectado.
            </div>
          ) : null}
          {revalidation.status === "dead" ? (
            <div className="mt-1 text-xs">
              Este arb ya no existe. La ejecución será bloqueada por el
              servidor.
            </div>
          ) : null}
        </div>
        <button
          onClick={onCheck}
          disabled={loading}
          className="rounded border border-current px-2 py-1 text-xs disabled:opacity-50"
        >
          Recheck
        </button>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: "bg-warn/20 text-warn",
    placed: "bg-accent/20 text-accent",
    confirmed: "bg-accent/20 text-accent",
    rejected: "bg-danger/20 text-danger",
    void: "bg-border text-muted",
  };
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs uppercase ${
        styles[status] ?? "bg-border text-muted"
      }`}
    >
      {status}
    </span>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1">{children}</div>
    </div>
  );
}
