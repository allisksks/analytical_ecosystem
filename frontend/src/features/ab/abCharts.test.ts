import { describe, expect, it } from "vitest";
import { densityCurves } from "./abCharts";

describe("densityCurves", () => {
  it("integrates to ~1 and peaks at the mean", () => {
    const { x, series } = densityCurves([
      { key: "A", mean: 0.2, sd: 0.01 },
      { key: "B", mean: 0.22, sd: 0.01 },
    ]);
    const step = x[1] - x[0];
    for (const s of series) expect(s.reduce((a, b) => a + b, 0) * step).toBeCloseTo(1, 1);
    const peak = x[series[1].indexOf(Math.max(...series[1]))];
    expect(peak).toBeCloseTo(0.22, 2);
  });

  it("handles degenerate posteriors", () => {
    expect(densityCurves([{ key: "A", mean: 0, sd: 0 }])).toEqual({ x: [], series: [] });
  });
});
