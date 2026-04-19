export function formatPct(value: number, digits = 2): string {
  return `${value.toFixed(digits)}%`;
}

const CURRENCY_LOCALE: Record<string, string> = {
  CLP: "es-CL",
  USD: "en-US",
  EUR: "es-ES",
  GBP: "en-GB",
};

/**
 * Formatea un monto con el símbolo/separadores apropiados para la moneda.
 * CLP por convención no usa decimales (Intl ya lo maneja).
 */
export function formatMoney(amount: number, currency: string): string {
  const locale = CURRENCY_LOCALE[currency] ?? "en-US";
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      // CLP sin decimales; USD/EUR con 2. Intl lo hace solo, pero el default
      // no siempre respeta — forzamos con maximumFractionDigits.
      maximumFractionDigits: currency === "CLP" ? 0 : 2,
      minimumFractionDigits: currency === "CLP" ? 0 : 2,
    }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
}

export function formatOdds(value: number): string {
  return value.toFixed(2);
}

export function formatDate(iso: string): string {
  const date = new Date(iso.includes("T") ? iso : iso.replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("es-ES", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function minutesUntil(iso: string): number {
  const date = new Date(iso.includes("T") ? iso : iso.replace(" UTC", "Z").replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return 0;
  return Math.max(0, Math.round((date.getTime() - Date.now()) / 60_000));
}
