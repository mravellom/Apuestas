"use client";

type Status = "active" | "expired";

interface Props {
  status: Status;
  minProfit: number;
  capital: number;
  onChange: (next: { status: Status; minProfit: number; capital: number }) => void;
  onRefresh: () => void;
  loading: boolean;
}

export function FilterBar({
  status,
  minProfit,
  capital,
  onChange,
  onRefresh,
  loading,
}: Props) {
  return (
    <div className="flex flex-wrap items-end gap-4 rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-col gap-1">
        <label className="text-xs uppercase tracking-wide text-muted">Estado</label>
        <select
          value={status}
          onChange={(e) =>
            onChange({ status: e.target.value as Status, minProfit, capital })
          }
          className="rounded border border-border bg-bg px-3 py-2 text-sm text-white"
        >
          <option value="active">Activas</option>
          <option value="expired">Expiradas</option>
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs uppercase tracking-wide text-muted">
          Profit mínimo (%)
        </label>
        <input
          type="number"
          step="0.1"
          min="0"
          value={minProfit}
          onChange={(e) =>
            onChange({ status, minProfit: Number(e.target.value), capital })
          }
          className="w-32 rounded border border-border bg-bg px-3 py-2 text-sm text-white"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs uppercase tracking-wide text-muted">
          Capital por arbitraje (€)
        </label>
        <input
          type="number"
          min="1"
          step="10"
          value={capital}
          onChange={(e) =>
            onChange({
              status,
              minProfit,
              capital: Math.max(1, Number(e.target.value) || 0),
            })
          }
          className="w-32 rounded border border-border bg-bg px-3 py-2 text-sm text-white"
        />
      </div>

      <button
        type="button"
        onClick={onRefresh}
        disabled={loading}
        className="rounded bg-accent px-4 py-2 text-sm font-medium text-bg hover:bg-accentHover disabled:opacity-50"
      >
        {loading ? "Cargando…" : "Refrescar"}
      </button>
    </div>
  );
}
