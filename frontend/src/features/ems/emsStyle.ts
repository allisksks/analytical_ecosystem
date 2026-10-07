import type { Tone } from "../../shared/ui";

export const STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  active: "pos",
  deprecated: "warn",
  archived: "neutral",
};
export const HEALTH_TONE: Record<string, Tone> = { ok: "pos", warning: "warn", critical: "neg", unknown: "neutral" };
export const SEVERITY_TONE: Record<string, Tone> = { warning: "warn", critical: "neg", info: "info" };
