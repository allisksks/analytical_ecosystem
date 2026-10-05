export interface Command {
  id: string;
  group: "pages" | "actions" | "events" | "experiments" | "dashboards" | "metrics" | "kb" | "ask";
  label: string;
  hint?: string;
  keywords?: string;
  to?: string;
  run?: () => void;
}

const norm = (s: string) => s.toLowerCase().replace(/ё/g, "е");

/** 3 — label starts with the query, 2 — a word of the label does, 1 — the query occurs anywhere. */
export function score(c: Command, query: string): number {
  const q = norm(query.trim());
  if (!q) return 1;
  const label = norm(c.label);
  if (label.startsWith(q)) return 3;
  if (label.split(/[\s_\-·/.]+/).some((w) => w.startsWith(q))) return 2;
  const hay = `${label} ${norm(c.hint ?? "")} ${norm(c.keywords ?? "")}`;
  return q.split(/\s+/).every((part) => hay.includes(part)) ? 1 : 0;
}

/** Keeps group order, sorts each group by score, caps entities so pages and actions stay visible. */
export function rank(commands: Command[], query: string, perGroup = 6): Command[] {
  const groups = new Map<string, { c: Command; s: number }[]>();
  for (const c of commands) {
    const s = score(c, query);
    if (s > 0) groups.set(c.group, [...(groups.get(c.group) ?? []), { c, s }]);
  }
  return [...groups.values()].flatMap((list) =>
    list
      .sort((a, b) => b.s - a.s)
      .slice(0, perGroup)
      .map((x) => x.c),
  );
}
