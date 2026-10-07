import type { Tone } from "../../shared/ui";
import { formatMoney, formatNumber, formatPercent } from "../../shared/lib/format";

export const STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  review: "warn",
  running: "info",
  completed: "pos",
  archived: "neutral",
};
export const REC_TONE: Record<string, Tone> = {
  collecting: "neutral",
  continue: "info",
  ship: "pos",
  keep_control: "neg",
  inconclusive: "warn",
  check_srm: "neg",
};
export const DECISION_TONE: Record<string, Tone> = { ship: "pos", keep_control: "neg", inconclusive: "warn" };

/** Metric value in its unit: proportions as %, money in $, counts as plain numbers. */
export function formatValue(v: number | null | undefined, unit: string, locale: string): string {
  if (unit === "%") return formatPercent(v, locale, 2);
  if (unit === "$") return formatMoney(v, locale);
  return formatNumber(v, locale, 2);
}

export function formatLift(v: number | null | undefined, locale: string): string {
  if (v === null || v === undefined) return "—";
  return (v > 0 ? "+" : "") + formatPercent(v, locale, 1);
}

export const liftTone = (v: number | null | undefined): "pos" | "neg" | "neutral" =>
  v === null || v === undefined || Math.abs(v) < 1e-9 ? "neutral" : v > 0 ? "pos" : "neg";
