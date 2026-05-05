"use client";

import Link from "next/link";

import { sportAccentColor } from "@/lib/sportColors";
import type { Arbitrage } from "@/lib/types";
import { formatDate, formatMoney, formatPct, minutesUntil } from "@/lib/format";

interface Props {
  arb: Arbitrage;
  capital: number;
  currency?: string;
}

export function ArbitrageCard({ arb, capital, currency = "USD" }: Props) {
  const minutes = minutesUntil(arb.commence_time);
  const guaranteed = capital * (1 + arb.profit_pct / 100);
  const netProfit = guaranteed - capital;
  const accent = sportAccentColor(arb.sport, arb.league);
  const leagueLabel = prettyLeague(arb.league, arb.sport);
  const point = arb.legs.find((l) => l.point != null)?.point ?? null;
  const marketLabel = point != null ? `${arb.market_type} ${point}` : arb.market_type;

  return (
    <article
      className="overflow-hidden rounded-lg border-2 bg-surface"
      style={{ borderColor: accent }}
    >
      {/* Header */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-bg px-5 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className="rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white"
              style={{ backgroundColor: accent }}
              title={`${arb.sport} · ${arb.league}`}
            >
              {leagueLabel}
            </span>
            <h3 className="truncate text-base font-semibold text-white">
              {arb.match}
            </h3>
            <span className="rounded bg-border px-2 py-0.5 text-[10px] uppercase text-muted">
              {marketLabel}
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
              <th className="px-3 py-2 text-right">A apostar</th>
              <th className="px-5 py-2 text-right">A cobrar</th>
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
                    {leg.point != null ? (
                      <span className="ml-1 text-muted">{leg.point}</span>
                    ) : null}
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
                    {formatMoney(stake, currency)}
                  </td>
                  <td className="px-5 py-2 text-right font-mono text-accent">
                    {formatMoney(payout, currency)}
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
          Invirtiendo <span className="font-mono text-white">{formatMoney(capital, currency)}</span>{" "}
          cobras{" "}
          <span className="font-mono text-accent">{formatMoney(guaranteed, currency)}</span> (beneficio
          neto <span className="font-mono text-accent">{formatMoney(netProfit, currency)}</span>)
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

const LEAGUE_LABELS: Record<string, string> = {
  soccer_epl: "EPL",
  soccer_spain_la_liga: "La Liga",
  soccer_italy_serie_a: "Serie A",
  soccer_italy_serie_b: "Serie B",
  soccer_germany_bundesliga: "Bundesliga",
  soccer_france_ligue_one: "Ligue 1",
  soccer_uefa_champs_league: "UCL",
  soccer_uefa_europa_league: "UEL",
  soccer_usa_mls: "MLS",
  soccer_england_championship: "Championship",
  soccer_brazil_campeonato: "Brasileirão",
  soccer_argentina_primera_division: "Arg Primera",
  soccer_chile_campeonato: "Chile",
  soccer_netherlands_eredivisie: "Eredivisie",
  soccer_portugal_primeira_liga: "Primeira",
  soccer_spain_segunda_division: "Segunda",
  soccer_england_efl_womens: "EFL W",
  soccer_usa_nwsl: "NWSL",
  baseball_mlb: "MLB",
  basketball_nba: "NBA",
  basketball_wnba: "WNBA",
  icehockey_nhl: "NHL",
  americanfootball_nfl: "NFL",
};

function prettyLeague(league: string, sport: string): string {
  return LEAGUE_LABELS[league] ?? sport.toUpperCase();
}
