import { describe, expect, it } from "vitest";
import { parseSse } from "./api";

describe("parseSse", () => {
  it("splits complete events and keeps the tail", () => {
    const { events, rest } = parseSse(
      'event: sources\ndata: [{"n":1}]\n\nevent: delta\ndata: "При"\n\nevent: delta\ndata: "вет',
    );
    expect(events).toEqual([
      { event: "sources", data: [{ n: 1 }] },
      { event: "delta", data: "При" },
    ]);
    expect(rest).toBe('event: delta\ndata: "вет');
    expect(parseSse(rest + '"\n\n').events).toEqual([{ event: "delta", data: "вет" }]);
  });
});
