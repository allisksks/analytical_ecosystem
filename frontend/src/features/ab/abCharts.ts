import type { EChartsCoreOption } from "../../shared/charts/echarts";
import type { ChartTheme } from "../../shared/charts/theme";

export interface Posterior {
  key: string;
  mean: number;
  sd: number;
}

/** Normal density on a shared grid covering ±4σ of every posterior. */
export function densityCurves(posteriors: Posterior[], points = 120): { x: number[]; series: number[][] } {
  const valid = posteriors.filter((p) => p.sd > 0 && Number.isFinite(p.mean));
  if (!valid.length) return { x: [], series: [] };
  const lo = Math.min(...valid.map((p) => p.mean - 4 * p.sd));
  const hi = Math.max(...valid.map((p) => p.mean + 4 * p.sd));
  const step = (hi - lo) / (points - 1);
  const x = Array.from({ length: points }, (_, i) => lo + i * step);
  const series = posteriors.map((p) =>
    x.map((v) => (p.sd > 0 ? Math.exp(-0.5 * ((v - p.mean) / p.sd) ** 2) / (p.sd * Math.sqrt(2 * Math.PI)) : 0)),
  );
  return { x, series };
}

export function posteriorOption(
  posteriors: Posterior[],
  fmt: (v: number) => string,
  theme: ChartTheme,
): EChartsCoreOption {
  const { x, series } = densityCurves(posteriors);
  return {
    color: theme.palette,
    textStyle: { fontFamily: theme.font, color: theme.ink2 },
    grid: { left: 12, right: 16, top: 32, bottom: 28, containLabel: true },
    legend: { top: 0, textStyle: { color: theme.ink2 } },
    tooltip: { trigger: "axis", valueFormatter: () => "", axisPointer: { type: "line" } },
    xAxis: {
      type: "category",
      data: x.map(fmt),
      boundaryGap: false,
      axisLine: { lineStyle: { color: theme.line } },
      axisLabel: { color: theme.ink3, interval: Math.floor(x.length / 6) },
    },
    yAxis: { type: "value", show: false },
    series: posteriors.map((p, i) => ({
      name: p.key,
      type: "line",
      data: series[i],
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 2 },
      areaStyle: { opacity: 0.15 },
    })),
  };
}

export function historyOption(
  points: { at: string; prob: number | null }[],
  threshold: number,
  fmtDate: (s: string) => string,
  theme: ChartTheme,
): EChartsCoreOption {
  return {
    color: theme.palette,
    textStyle: { fontFamily: theme.font, color: theme.ink2 },
    grid: { left: 12, right: 24, top: 16, bottom: 24, containLabel: true },
    tooltip: { trigger: "axis", valueFormatter: (v: number) => (v * 100).toFixed(1) + "%" },
    xAxis: {
      type: "category",
      data: points.map((p) => fmtDate(p.at)),
      axisLine: { lineStyle: { color: theme.line } },
      axisLabel: { color: theme.ink3 },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 1,
      axisLabel: { color: theme.ink3, formatter: (v: number) => `${Math.round(v * 100)}%` },
      splitLine: { lineStyle: { color: theme.line } },
    },
    series: [
      {
        name: "P",
        type: "line",
        data: points.map((p) => p.prob),
        showSymbol: points.length < 30,
        lineStyle: { width: 2 },
        markLine: {
          symbol: "none",
          silent: true,
          lineStyle: { type: "dashed", color: theme.ink3 },
          label: { formatter: `${Math.round(threshold * 100)}%`, color: theme.ink3 },
          data: [{ yAxis: threshold }, { yAxis: 1 - threshold }],
        },
      },
    ],
  };
}
