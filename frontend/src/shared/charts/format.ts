import { formatCompact, formatMoney, formatNumber, formatPercent } from "../lib/format";

export type ValueFormat = "number" | "percent" | "currency" | "decimal" | "";

export function formatValue(v: unknown, fmt: ValueFormat | string, locale: string, compact = false): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v !== "number") return String(v);
  switch (fmt) {
    case "percent":
      return formatPercent(v, locale, 1);
    case "currency":
      return compact && Math.abs(v) >= 10_000 ? `$${formatCompact(v, locale)}` : formatMoney(v, locale);
    case "decimal":
      return formatNumber(v, locale, 2);
    default:
      return compact && Math.abs(v) >= 10_000
        ? formatCompact(v, locale)
        : formatNumber(v, locale, Math.abs(v) < 10 ? 2 : 0);
  }
}
