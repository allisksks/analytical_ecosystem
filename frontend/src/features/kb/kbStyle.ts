import type { Tone } from "../../shared/ui";

export const TYPE_TONE: Record<string, Tone> = {
  experiment: "violet",
  research: "info",
  case: "pos",
  incident_report: "neg",
  playbook: "info",
  decision_log: "warn",
  metric_definition: "neutral",
};

export const DECISION_TONE: Record<string, Tone> = { accepted: "pos", rejected: "neg", inconclusive: "warn" };
export const KB_TYPES = [
  "experiment",
  "research",
  "case",
  "incident_report",
  "playbook",
  "decision_log",
  "metric_definition",
] as const;
