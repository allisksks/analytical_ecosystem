import { buildOption, toSeries, type ChartData } from "./buildOption";
import type { ChartTheme } from "./theme";

const theme: ChartTheme = {
  palette: ["#111111", "#222222", "#333333", "#444444", "#555555", "#666666", "#777777", "#888888"],
  ink: "#000",
  ink2: "#111",
  ink3: "#222",
  line: "#eee",
  surface: "#fff",
  brand: "#00f",
  font: "sans-serif",
};

const cohorts: ChartData = {
  columns: [
    { key: "cohort", name: "Когорта", role: "dimension", format: "" },
    { key: "day_n", name: "День", role: "dimension", format: "" },
    { key: "retention_curve", name: "Кривая", role: "metric", format: "percent" },
  ],
  rows: [
    ["A", 0, 1],
    ["A", 1, 0.5],
    ["A", 10, 0.1],
    ["B", 0, 1],
    ["B", 1, 0.4],
    ["B", 2, 0.3],
  ],
};

describe("toSeries", () => {
  it("uses the dimension, not the cohort label, as x axis and sorts numeric categories", () => {
    const { x, categories, series } = toSeries(cohorts);
    expect(x?.key).toBe("day_n");
    expect(categories).toEqual(["0", "1", "2", "10"]);
    expect(series.map((s) => s.name)).toEqual(["A", "B"]);
  });

  it("caps series at 8 and keeps colour order stable (alphabetical, not by rank)", () => {
    const rows = Array.from({ length: 12 }, (_, i) => ["2026-01-01", `g${String(i).padStart(2, "0")}`, i + 1]);
    const data: ChartData = {
      columns: [
        { key: "period", name: "Период", role: "period", format: "" },
        { key: "app_id", name: "Игра", role: "dimension", format: "" },
        { key: "revenue", name: "Выручка", role: "metric", format: "currency" },
      ],
      rows,
    };
    const { series } = toSeries(data);
    expect(series).toHaveLength(8);
    expect(series[0].name).toBe("g04");
  });
});

describe("buildOption", () => {
  it("builds a single-axis line chart with a legend for several series", () => {
    const opt = buildOption("line", cohorts, {}, "ru", theme) as { yAxis: object; legend?: object; series: unknown[] };
    expect(Array.isArray(opt.yAxis)).toBe(false);
    expect(opt.legend).toBeDefined();
    expect(opt.series).toHaveLength(2);
  });

  it("builds a heatmap with a single-hue sequential scale", () => {
    const opt = buildOption("heatmap", cohorts, {}, "ru", theme) as { visualMap: { inRange: { color: string[] } } };
    expect(opt.visualMap.inRange.color).toEqual(["#fff", "#111111"]);
  });
});
