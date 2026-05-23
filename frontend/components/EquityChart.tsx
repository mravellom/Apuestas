"use client";

import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getPaperEquityCurve } from "@/lib/api";
import type { PaperEquityCurve } from "@/lib/api";

interface Props {
  sourceType?: "value" | "arbitrage";
  /** Altura del chart en px. Default 280. */
  height?: number;
}

/** Curva de P&L acumulado de paper trading con DD highlighted.
 *
 * Se usa para validar visualmente si el edge se degrada con el tiempo:
 *   - Línea verde subiendo  → el detector tiene edge real
 *   - Plateau prolongado    → el edge se erosionó (limit, ToS change, etc.)
 *   - Drawdown grande       → riesgo de variance — revisar staking
 *
 * Refetch implícito vía el polling de la página padre.
 */
export function EquityChart({ sourceType, height = 280 }: Props) {
  const [data, setData] = useState<PaperEquityCurve | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    getPaperEquityCurve(sourceType)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Error cargando equity curve");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sourceType]);

  if (error) {
    return (
      <div className="rounded-lg border border-red-900/50 bg-red-950/20 p-4 text-sm text-red-300">
        Error: {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div
        className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-sm text-muted"
        style={{ height }}
      >
        Cargando curva de equity…
      </div>
    );
  }

  if (data.points.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-sm text-muted"
        style={{ height }}
      >
        Aún no hay apuestas resueltas — la curva aparece cuando se settleen.
      </div>
    );
  }

  // Formato de datos para recharts. Numbers limpios para tooltip + axis.
  const chartData = data.points.map((p, i) => ({
    idx: i + 1,
    timestamp: p.timestamp,
    cumulative: p.cumulative_profit,
    drawdown: -p.drawdown_units, // negativo para mostrar bajo el eje 0
  }));

  const last = data.points[data.points.length - 1];

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      {/* KPIs */}
      <div className="mb-3 grid grid-cols-3 gap-2 text-xs">
        <div>
          <div className="text-muted">P&L actual</div>
          <div
            className={`text-base font-semibold ${
              last.cumulative_profit >= 0 ? "text-green-400" : "text-red-400"
            }`}
          >
            {last.cumulative_profit >= 0 ? "+" : ""}
            {last.cumulative_profit.toFixed(3)} u
          </div>
        </div>
        <div>
          <div className="text-muted">Max drawdown</div>
          <div className="text-base font-semibold text-amber-400">
            −{data.max_drawdown_units.toFixed(3)} u
          </div>
        </div>
        <div>
          <div className="text-muted">Sharpe proxy</div>
          <div className="text-base font-semibold text-white">
            {data.sharpe_proxy === null
              ? "—"
              : data.sharpe_proxy.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={chartData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <defs>
            <linearGradient id="eqProfit" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#22c55e" stopOpacity={0.45} />
              <stop offset="100%" stopColor="#22c55e" stopOpacity={0.02} />
            </linearGradient>
            <linearGradient id="eqDd" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.0} />
              <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.30} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
          <XAxis
            dataKey="idx"
            tick={{ fill: "#64748b", fontSize: 11 }}
            stroke="#334155"
            label={{
              value: "# apuesta",
              position: "insideBottom",
              offset: -2,
              fill: "#64748b",
              fontSize: 11,
            }}
          />
          <YAxis
            tick={{ fill: "#64748b", fontSize: 11 }}
            stroke="#334155"
            tickFormatter={(v: number) => v.toFixed(2)}
          />
          <Tooltip
            contentStyle={{
              background: "#0f172a",
              border: "1px solid #334155",
              borderRadius: 6,
              fontSize: 12,
            }}
            labelFormatter={(_label, payload) => {
              const p = payload?.[0]?.payload;
              if (!p) return "";
              const ts = p.timestamp ? new Date(p.timestamp).toLocaleString() : "";
              return `Apuesta #${p.idx} · ${ts}`;
            }}
            formatter={(value: number, name: string) => {
              if (name === "cumulative") return [`${value.toFixed(3)} u`, "P&L"];
              if (name === "drawdown") return [`${value.toFixed(3)} u`, "Drawdown"];
              return [value, name];
            }}
          />
          {/* DD por debajo del 0 (visualmente debajo del flujo de equity) */}
          <Area
            type="monotone"
            dataKey="drawdown"
            stroke="#f59e0b"
            strokeWidth={1}
            fill="url(#eqDd)"
          />
          {/* P&L acumulado: línea + área verde */}
          <Area
            type="monotone"
            dataKey="cumulative"
            stroke="#22c55e"
            strokeWidth={2}
            fill="url(#eqProfit)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
