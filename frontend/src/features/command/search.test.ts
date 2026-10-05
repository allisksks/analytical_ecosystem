import { describe, expect, it } from "vitest";
import { rank, score, type Command } from "./search";

const cmd = (label: string, group: Command["group"] = "pages", hint = ""): Command => ({
  id: label,
  label,
  group,
  hint,
});

describe("command search", () => {
  it("prefers prefix, then word start, then substring", () => {
    expect(score(cmd("Дашборды"), "даш")).toBe(3);
    expect(score(cmd("level_complete", "events"), "comp")).toBe(2);
    expect(score(cmd("Реестр событий", "pages", "events tracking"), "track")).toBe(1);
    expect(score(cmd("Реестр"), "xyz")).toBe(0);
    expect(score(cmd("Ёлка"), "елк")).toBe(3);
  });

  it("keeps group order and caps groups", () => {
    const list = [cmd("SQL-редактор"), ...Array.from({ length: 10 }, (_, i) => cmd(`sql_event_${i}`, "events"))];
    const out = rank(list, "sql", 3);
    expect(out[0].label).toBe("SQL-редактор");
    expect(out).toHaveLength(4);
  });
});
