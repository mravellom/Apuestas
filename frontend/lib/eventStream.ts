"use client";

import { useEffect } from "react";

import { getToken } from "@/lib/auth";

type EventHandlers = {
  /** Llamado con el id de la nueva ArbitrageOpportunity cuando llega un evento `arbitrage`. */
  onArbitrage?: (id: number) => void;
  /** Llamado con el id de la nueva Opportunity (value bet) cuando llega un evento `value`. */
  onValue?: (id: number) => void;
};

/**
 * Suscribe el componente al stream SSE de `/api/v1/stream/opportunities`.
 *
 * Reemplaza el polling de 60s del listado: cuando `detect_arbitrage_job` o
 * `detect_value_job` insertan oportunidades nuevas, el bus las pushea y
 * acá llamamos al callback (típicamente `() => void refetch()`).
 *
 * Auth: token va en `?token=` en la URL — EventSource del browser no
 * permite headers HTTP custom, así que JWT por query es el patrón estándar.
 *
 * Reconexión: el navegador la maneja sola (default ~3s entre intentos).
 */
export function useOpportunityStream(handlers: EventHandlers): void {
  const { onArbitrage, onValue } = handlers;

  useEffect(() => {
    const token = getToken();
    if (!token) return;

    const url = `/api/v1/stream/opportunities?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);

    const arbHandler = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as { id?: number };
        if (typeof data.id === "number" && onArbitrage) onArbitrage(data.id);
      } catch {
        // payload malformado — ignorar silenciosamente, no romper la conexión
      }
    };
    const valHandler = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as { id?: number };
        if (typeof data.id === "number" && onValue) onValue(data.id);
      } catch {
        // idem
      }
    };

    if (onArbitrage) es.addEventListener("arbitrage", arbHandler);
    if (onValue) es.addEventListener("value", valHandler);

    es.onerror = () => {
      // EventSource auto-reconnect; logueamos en debug solamente para no
      // spammear la consola en redes intermitentes.
      // eslint-disable-next-line no-console
      if (process.env.NEXT_PUBLIC_DEBUG_SSE) console.debug("[SSE] error/reconnect");
    };

    return () => {
      if (onArbitrage) es.removeEventListener("arbitrage", arbHandler);
      if (onValue) es.removeEventListener("value", valHandler);
      es.close();
    };
  }, [onArbitrage, onValue]);
}
