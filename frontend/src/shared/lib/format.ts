/** Locale-aware number/date formatting helpers shared by tables, KPI tiles and charts. */
const nf = new Map<string, Intl.NumberFormat>();

function fmt(locale: string, opts: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = locale + JSON.stringify(opts);
  let f = nf.get(key);
  if (!f) {
    f = new Intl.NumberFormat(locale, opts);
    nf.set(key, f);
  }
  return f;
}

export function formatNumber(v: number | null | undefined, locale = "ru", digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return fmt(locale, { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(v);
}

export function formatCompact(v: number | null | undefined, locale = "ru"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return fmt(locale, { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

export function formatPercent(v: number | null | undefined, locale = "ru", digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return fmt(locale, { style: "percent", maximumFractionDigits: digits, minimumFractionDigits: digits }).format(v);
}

export function formatMoney(v: number | null | undefined, locale = "ru", currency = "USD"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return fmt(locale, { style: "currency", currency, maximumFractionDigits: 2 }).format(v);
}

export function formatDate(v: string | number | Date | null | undefined, locale = "ru"): string {
  if (!v) return "—";
  const d = v instanceof Date ? v : new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" });
}

export function formatDateTime(v: string | number | Date | null | undefined, locale = "ru"): string {
  if (!v) return "—";
  const d = v instanceof Date ? v : new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}
