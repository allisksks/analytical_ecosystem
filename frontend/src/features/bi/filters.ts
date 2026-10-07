import type { FilterState } from "./FilterBar";

export const PRESETS = [7, 30, 90] as const;
export type Preset = (typeof PRESETS)[number] | "custom";

export function isoDaysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60_000).toISOString().slice(0, 10);
}

export function defaultFilters(periodDays = 30): FilterState {
  const preset = (PRESETS as readonly number[]).includes(periodDays) ? (periodDays as Preset) : 30;
  const days = preset === "custom" ? 30 : preset;
  return { preset, date_from: isoDaysAgo(days - 1), date_to: isoDaysAgo(0), filters: [] };
}

export function toGlobal(f: FilterState) {
  return { date_from: f.date_from, date_to: f.date_to, filters: f.filters };
}
