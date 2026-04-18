export function formatPct(value: number, digits = 2): string {
  return `${value.toFixed(digits)}%`;
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
