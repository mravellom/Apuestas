"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Header } from "@/components/Header";
import { createBankroll, listBankrolls } from "@/lib/api";
import { isAuthenticated } from "@/lib/auth";
import { formatMoney } from "@/lib/format";
import type { Bankroll } from "@/lib/types";

export default function BankrollPage() {
  const router = useRouter();
  const [bankrolls, setBankrolls] = useState<Bankroll[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "Principal",
    currency: "USD",
    initial_amount: 1000,
  });
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    refresh();
  }, [router]);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const brs = await listBankrolls();
      setBankrolls(brs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error cargando bankrolls");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await createBankroll(form);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error creando bankroll");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="min-h-screen">
      <Header />
      <main className="mx-auto max-w-4xl px-6 py-8">
        <h1 className="mb-6 text-2xl font-bold text-white">Bankroll</h1>

        {error ? (
          <p className="mb-4 rounded border border-danger/40 bg-danger/10 p-2 text-sm text-danger">
            {error}
          </p>
        ) : null}

        <section className="mb-8 rounded-lg border border-border bg-surface p-6">
          <h2 className="mb-4 text-lg font-semibold text-white">Bankrolls activos</h2>
          {loading ? (
            <p className="text-muted">Cargando…</p>
          ) : bankrolls.length === 0 ? (
            <p className="text-muted">
              No tienes bankrolls. Crea uno abajo para poder ejecutar arbitrajes.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-border text-sm">
                <thead className="bg-bg text-xs uppercase tracking-wide text-muted">
                  <tr>
                    <th className="px-3 py-2 text-left">Nombre</th>
                    <th className="px-3 py-2 text-left">Moneda</th>
                    <th className="px-3 py-2 text-right">Inicial</th>
                    <th className="px-3 py-2 text-right">Actual</th>
                    <th className="px-3 py-2 text-right">Reservado</th>
                    <th className="px-3 py-2 text-right">Disponible</th>
                    <th className="px-3 py-2 text-right">P&amp;L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {bankrolls.map((b) => {
                    const pnl = b.current_amount - b.initial_amount;
                    const pnlColor =
                      pnl > 0
                        ? "text-accent"
                        : pnl < 0
                          ? "text-danger"
                          : "text-muted";
                    return (
                      <tr key={b.id}>
                        <td className="px-3 py-2 text-white">{b.name}</td>
                        <td className="px-3 py-2 font-mono">{b.currency}</td>
                        <td className="px-3 py-2 text-right font-mono text-muted">
                          {formatMoney(b.initial_amount, b.currency)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-white">
                          {formatMoney(b.current_amount, b.currency)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-warn">
                          {formatMoney(b.reserved_amount, b.currency)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-accent">
                          {formatMoney(b.available_amount, b.currency)}
                        </td>
                        <td className={`px-3 py-2 text-right font-mono ${pnlColor}`}>
                          {pnl >= 0 ? "+" : ""}
                          {formatMoney(pnl, b.currency)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="rounded-lg border border-border bg-surface p-6">
          <h2 className="mb-4 text-lg font-semibold text-white">Crear nuevo bankroll</h2>
          <form onSubmit={handleCreate} className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label className="block text-xs uppercase tracking-wide text-muted">
                Nombre
              </label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wide text-muted">
                Moneda
              </label>
              <select
                value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value })}
                className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 text-sm text-white"
              >
                <option value="USD">USD</option>
                <option value="EUR">EUR</option>
                <option value="CLP">CLP</option>
              </select>
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wide text-muted">
                Monto inicial
              </label>
              <input
                type="number"
                min="1"
                value={form.initial_amount}
                onChange={(e) =>
                  setForm({
                    ...form,
                    initial_amount: Math.max(1, Number(e.target.value) || 0),
                  })
                }
                className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 text-sm text-white"
              />
            </div>
            <div className="sm:col-span-3">
              <button
                type="submit"
                disabled={creating}
                className="rounded bg-accent px-4 py-2 text-sm font-semibold text-bg disabled:opacity-50"
              >
                {creating ? "Creando…" : "Crear"}
              </button>
            </div>
          </form>
        </section>
      </main>
    </div>
  );
}
