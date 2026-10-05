import type { EChartsCoreOption } from "./echarts";
import { formatValue } from "./format";
import type { ChartTheme } from "./theme";

export interface DataColumn {
  key: string;
  name: string;
  role: string; // period | dimension | metric
  format: string;
}

export interface ChartData {
  columns: DataColumn[];
  rows: unknown[][];
}

export type Viz = "line" | "bar" | "area" | "heatmap" | "table" | "kpi" | "pie";

export interface ChartSettings {
  stacked?: boolean;
}

const MAX_SERIES = 8;

interface Series {
  name: string;
  metric: DataColumn;
  points: Map<string, number | null>;
  total: number;
}

function label(v: unknown): string {
  return v === null || v === undefined ? "—" : String(v);
}

/** Splits a semantic result into x axis + series (metric × combination of the remaining dimensions). */
export function toSeries(data: ChartData): { x: DataColumn | undefined; categories: string[]; series: Series[] } {
  const idx = new Map(data.columns.map((c, i) => [c.key, i]));
  // x axis: time if present, otherwise the first real dimension (a cohort label is a series, never the axis)
  const x =
    data.columns.find((c) => c.role === "period") ??
    data.columns.find((c) => c.role === "dimension" && c.key !== "cohort") ??
    data.columns.find((c) => c.role === "dimension");
  const splits = data.columns.filter((c) => c.role !== "metric" && c !== x);
  const metrics = data.columns.filter((c) => c.role === "metric");
  const categories: string[] = [];
  const seen = new Set<string>();
  const byName = new Map<string, Series>();
  for (const row of data.rows) {
    const cat = x ? label(row[idx.get(x.key)!]) : "";
    if (!seen.has(cat)) {
      seen.add(cat);
      categories.push(cat);
    }
    const split = splits.map((s) => label(row[idx.get(s.key)!])).join(" · ");
    for (const m of metrics) {
      const name = [metrics.length > 1 || !split ? m.name : "", split].filter(Boolean).join(" · ");
      let s = byName.get(name);
      if (!s) {
        s = { name, metric: m, points: new Map(), total: 0 };
        byName.set(name, s);
      }
      const v = row[idx.get(m.key)!];
      const num = typeof v === "number" ? v : v === null || v === undefined ? null : Number(v);
      s.points.set(cat, num);
      s.total += Math.abs(num ?? 0);
    }
  }
  if (x?.role === "dimension" && categories.every((c) => c !== "" && !Number.isNaN(Number(c)))) {
    categories.sort((a, b) => Number(a) - Number(b));
  }
  // keep the most significant series, then restore a stable (alphabetical) order so colour follows the entity
  const series = [...byName.values()]
    .sort((a, b) => b.total - a.total)
    .slice(0, MAX_SERIES)
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
  return { x, categories, series };
}

function baseAxis(theme: ChartTheme) {
  return {
    axisLine: { lineStyle: { color: theme.line } },
    axisTick: { show: false },
    axisLabel: { color: theme.ink3, fontFamily: theme.font, fontSize: 11 },
    splitLine: { lineStyle: { color: theme.line } },
  };
}

export function buildOption(
  viz: Viz,
  data: ChartData,
  settings: ChartSettings,
  locale: string,
  theme: ChartTheme,
): EChartsCoreOption {
  if (viz === "heatmap") return heatmap(data, locale, theme);
  const { categories, series } = toSeries(data);
  const fmt = series[0]?.metric.format ?? "";
  const type = viz === "area" ? "line" : viz === "pie" ? "bar" : viz;
  const stacked = settings.stacked && series.length > 1;
  return {
    color: theme.palette,
    textStyle: { fontFamily: theme.font, color: theme.ink2 },
    animationDuration: 300,
    grid: { left: 8, right: 16, top: series.length > 1 ? 36 : 12, bottom: 8, containLabel: true },
    legend:
      series.length > 1
        ? {
            top: 0,
            left: 0,
            type: "scroll",
            icon: "roundRect",
            itemWidth: 12,
            itemHeight: 4,
            textStyle: { color: theme.ink2 },
          }
        : undefined,
    tooltip: {
      trigger: "axis",
      axisPointer: { type: type === "bar" ? "shadow" : "line", lineStyle: { color: theme.ink3 } },
      backgroundColor: theme.surface,
      borderColor: theme.line,
      textStyle: { color: theme.ink, fontFamily: theme.font, fontSize: 12 },
      valueFormatter: (v: unknown) => formatValue(v, fmt, locale),
    },
    xAxis: {
      type: "category",
      data: categories,
      boundaryGap: type === "bar",
      ...baseAxis(theme),
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      ...baseAxis(theme),
      axisLabel: { ...baseAxis(theme).axisLabel, formatter: (v: number) => formatValue(v, fmt, locale, true) },
    },
    series: series.map((s) => ({
      name: s.name,
      type,
      data: categories.map((c) => s.points.get(c) ?? null),
      stack: stacked ? "total" : undefined,
      showSymbol: false,
      symbolSize: 8,
      connectNulls: false,
      lineStyle: { width: 2 },
      areaStyle: viz === "area" ? { opacity: stacked ? 0.55 : 0.15 } : undefined,
      barMaxWidth: 28,
      itemStyle:
        type === "bar"
          ? { borderRadius: stacked ? 0 : [4, 4, 0, 0], borderColor: theme.surface, borderWidth: stacked ? 1 : 0 }
          : undefined,
      emphasis: { focus: "series" },
    })),
  };
}

function heatmap(data: ChartData, locale: string, theme: ChartTheme): EChartsCoreOption {
  const idx = new Map(data.columns.map((c, i) => [c.key, i]));
  const dims = data.columns.filter((c) => c.role !== "metric");
  const metric = data.columns.find((c) => c.role === "metric");
  // x: the "along" dimension (e.g. day_n), y: period or the other dimension (e.g. install week)
  const xCol = dims.find((c) => c.role === "dimension") ?? dims[0];
  const yCol = dims.find((c) => c !== xCol);
  if (!xCol || !yCol || !metric) return {};
  const xs = [...new Set(data.rows.map((r) => label(r[idx.get(xCol.key)!])))].sort((a, b) => Number(a) - Number(b));
  const ys = [...new Set(data.rows.map((r) => label(r[idx.get(yCol.key)!])))].sort();
  const values = data.rows.map((r) => [
    xs.indexOf(label(r[idx.get(xCol.key)!])),
    ys.indexOf(label(r[idx.get(yCol.key)!])),
    r[idx.get(metric.key)!] as number,
  ]);
  const max = Math.max(...values.map((v) => Number(v[2]) || 0), 0);
  return {
    textStyle: { fontFamily: theme.font, color: theme.ink2 },
    grid: { left: 8, right: 8, top: 8, bottom: 40, containLabel: true },
    tooltip: {
      backgroundColor: theme.surface,
      borderColor: theme.line,
      textStyle: { color: theme.ink, fontSize: 12 },
      formatter: (p: { value: [number, number, number] }) =>
        `${yCol.name}: ${ys[p.value[1]]}<br/>${xCol.name}: ${xs[p.value[0]]}<br/><b>${formatValue(p.value[2], metric.format, locale)}</b>`,
    },
    xAxis: { type: "category", data: xs, ...baseAxis(theme), splitArea: { show: false } },
    yAxis: { type: "category", data: ys, ...baseAxis(theme), splitArea: { show: false } },
    visualMap: {
      min: 0,
      max: max || 1,
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemHeight: 120,
      itemWidth: 10,
      textStyle: { color: theme.ink3, fontSize: 11 },
      formatter: (v: number) => formatValue(v, metric.format, locale, true),
      // sequential = one hue, light -> dark
      inRange: { color: [theme.surface, theme.palette[0]] },
    },
    series: [
      {
        type: "heatmap",
        data: values,
        itemStyle: { borderColor: theme.surface, borderWidth: 2, borderRadius: 2 },
        emphasis: { itemStyle: { borderColor: theme.ink } },
      },
    ],
  };
}
