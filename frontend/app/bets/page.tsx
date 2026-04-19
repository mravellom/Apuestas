"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Header } from "@/components/Header";
import { listBets, settleBet } from "@/lib/api";
import { isAuthenticated } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import type { Bet, BetResult, BetStatus } from "@/lib/types";

const STATUS_FILTERS: { value: BetStatus | "all"; label: string }[] = [
  { value: "all", label: "Todas" },
  { value: "pending", label: "Pending" },
  { value: "placed", label: "Placed" },
  { value: "settled", label: "Liquidadas" },
  { value: "rejected", label: "Rejected" },
];

export default function BetsPage() {
  const router = useRouter();
  const [bets, setBets] = useState<Bet[]>([]);
  const [status, setStatus] = useState<BetStatus | "all">("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    refresh();
  }, [router, status]);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const data = await listBets({
        status: status === "all" ? undefined : status,
      });
      setBets(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error cargando apuestas");
    } finally {
      setLoading(false);
    }
  }

  const placedUnresolved = bets.filter(
    (b) => (b.status === "placed" || b.status === "confirmed") && !b.result,
  );

  return (
    <div className="min-h-screen">
      <Header />
      <main className="mx-auto max-w-6xl px-6 py-8">
        <h1 className="mb-6 text-2xl font-bold text-white">Mis apuestas</h1>

        {error ? (
          <p className="mb-4 rounded border border-danger/40 bg-danger/10 p-2 text-sm text-danger">
            {error}
          </p>
        ) : null}

        <div className="mb-4 flex gap-2">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setStatus(f.value)}
              className={`rounded px-3 py-1 text-sm ${
                status === f.value
                  ? "bg-accent text-bg"
                  : "border border-border text-muted hover:text-white"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {placedUnresolved.length > 0 ? (
          <div className="mb-6 rounded border border-warn/40 bg-warn/10 p-3 text-sm text-warn">
            Tienes {placedUnresolved.length} apuesta(s) colocadas sin liquidar.
            Revísalas cuando termine el partido para registrar resultado real.
          </div>
        ) : null}

        {loading ? (
          <p className="text-muted">Cargando…</p>
        ) : bets.length === 0 ? (
          <p className="text-muted">No hay apuestas con el filtro actual.</p>
        ) : (
          <div className="space-y-3">
            {bets.map((bet) => (
              <BetRow key={bet.id} bet={bet} onChanged={refresh} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function BetRow({ bet, onChanged }: { bet: Bet; onChanged: () => void }) {
  const [settleOpen, setSettleOpen] = useState(false);
  const [result, setResult] = useState<BetResult>("won");
  const [payout, setPayout] = useState(
    bet.odds_at_placement ? bet.stake_amount * bet.odds_at_placement : 0,
  );
  const [working, setWorking] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handleSettle() {
    setWorking(true);
    setErr(null);
    try {
      await settleBet(bet.id, result, payout);
      setSettleOpen(false);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error liquidando");
    } finally {
      setWorking(false);
    }
  }

  const canSettle =
    (bet.status === "placed" || bet.status === "confirmed") && !bet.result;

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <span className="text-xs uppercase tracking-wide text-muted">
            {bet.arbitrage_id ? `Arb #${bet.arbitrage_id}` : "Value bet"} · Bet #
            {bet.id}
          </span>
          <div className="text-sm text-white">
            Stake{" "}
            <span className="font-mono">{bet.stake_amount.toFixed(2)}</span> ·
            Cuota{" "}
            <span className="font-mono">
              {bet.odds_at_placement?.toFixed(2) ?? "?"}
            </span>
            {bet.odds_at_detection !== null &&
            bet.odds_at_detection !== bet.odds_at_placement ? (
              <span className="text-muted">
                {" "}
                (detectada {bet.odds_at_detection.toFixed(2)})
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span
            className={`rounded px-2 py-0.5 uppercase ${statusStyle(bet.status)}`}
          >
            {bet.status}
          </span>
          {bet.result ? (
            <span
              className={`rounded px-2 py-0.5 uppercase ${resultStyle(bet.result)}`}
            >
              {bet.result}
            </span>
          ) : null}
          {bet.profit_loss !== null ? (
            <span
              className={`font-mono ${
                bet.profit_loss >= 0 ? "text-accent" : "text-danger"
              }`}
            >
              {bet.profit_loss >= 0 ? "+" : ""}
              {bet.profit_loss.toFixed(2)}
            </span>
          ) : null}
        </div>
      </div>

      <div className="mt-1 text-xs text-muted">
        Creada {formatDate(bet.created_at)}
        {bet.placed_at ? ` · Colocada ${formatDate(bet.placed_at)}` : ""}
        {bet.settled_at ? ` · Liquidada ${formatDate(bet.settled_at)}` : ""}
      </div>

      {canSettle ? (
        <div className="mt-3">
          {!settleOpen ? (
            <button
              onClick={() => setSettleOpen(true)}
              className="rounded bg-accent px-3 py-1 text-sm font-medium text-bg"
            >
              Liquidar
            </button>
          ) : (
            <div className="space-y-2 rounded border border-border bg-bg/50 p-3">
              {err ? <p className="text-sm text-danger">{err}</p> : null}
              <div className="flex flex-wrap items-end gap-2">
                <div>
                  <label className="block text-xs uppercase tracking-wide text-muted">
                    Resultado
                  </label>
                  <select
                    value={result}
                    onChange={(e) => setResult(e.target.value as BetResult)}
                    className="mt-1 rounded border border-border bg-bg px-2 py-1 text-sm text-white"
                  >
                    <option value="won">Ganada</option>
                    <option value="lost">Perdida</option>
                    <option value="void">Anulada</option>
                    <option value="half_won">Medio ganada</option>
                    <option value="half_lost">Medio perdida</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs uppercase tracking-wide text-muted">
                    Payout real
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={payout}
                    onChange={(e) =>
                      setPayout(Math.max(0, Number(e.target.value) || 0))
                    }
                    className="mt-1 rounded border border-border bg-bg px-2 py-1 text-sm text-white"
                  />
                </div>
                <button
                  onClick={handleSettle}
                  disabled={working}
                  className="rounded bg-accent px-3 py-1 text-sm font-medium text-bg disabled:opacity-50"
                >
                  Guardar
                </button>
                <button
                  onClick={() => setSettleOpen(false)}
                  disabled={working}
                  className="rounded border border-border px-3 py-1 text-sm text-muted"
                >
                  Cancelar
                </button>
              </div>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function statusStyle(s: BetStatus): string {
  switch (s) {
    case "pending":
      return "bg-warn/20 text-warn";
    case "placed":
    case "confirmed":
      return "bg-accent/20 text-accent";
    case "settled":
      return "bg-border/40 text-white";
    case "rejected":
      return "bg-danger/20 text-danger";
    default:
      return "bg-border text-muted";
  }
}

function resultStyle(r: BetResult): string {
  switch (r) {
    case "won":
    case "half_won":
      return "bg-accent/20 text-accent";
    case "lost":
    case "half_lost":
      return "bg-danger/20 text-danger";
    default:
      return "bg-border text-muted";
  }
}
