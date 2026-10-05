import { useEffect, useRef } from "react";
import { useTheme } from "../lib/theme";
import { echarts, type EChartsCoreOption } from "./echarts";
import { readTheme, type ChartTheme } from "./theme";

export interface EChartHandle {
  toDataURL: () => string | undefined;
}

/** Thin React wrapper: owns the instance, resizes with its container, re-themes on theme switch. */
export function EChart({
  build,
  height = "100%",
  label,
  onReady,
}: {
  build: (theme: ChartTheme) => EChartsCoreOption;
  height?: number | string;
  label: string;
  onReady?: (h: EChartHandle) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<ReturnType<typeof echarts.init> | null>(null);
  const { resolved } = useTheme();

  useEffect(() => {
    if (!host.current) return;
    const c = echarts.init(host.current, undefined, { renderer: "svg" });
    chart.current = c;
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(host.current);
    onReady?.({ toDataURL: () => c.getDataURL({ type: "svg", backgroundColor: readTheme().surface }) });
    return () => {
      ro.disconnect();
      c.dispose();
      chart.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    chart.current?.setOption(build(readTheme()), { notMerge: true });
  }, [build, resolved]);

  return <div ref={host} role="img" aria-label={label} style={{ width: "100%", height }} />;
}
