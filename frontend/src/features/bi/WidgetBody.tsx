import { useCallback } from "react";
import { buildOption, type ChartData, type ChartSettings, type Viz } from "../../shared/charts/buildOption";
import { EChart, type EChartHandle } from "../../shared/charts/EChart";
import { formatValue } from "../../shared/charts/format";
import type { ChartTheme } from "../../shared/charts/theme";
import { useI18n } from "../../shared/i18n";
import { Table, tableStyles } from "../../shared/ui";
import s from "./bi.module.css";

export function DataTable({ data, maxHeight = "100%" }: { data: ChartData; maxHeight?: number | string }) {
  const { locale } = useI18n();
  return (
    <Table compact maxHeight={maxHeight}>
      <thead>
        <tr>
          {data.columns.map((c) => (
            <th key={c.key} className={c.role === "metric" ? tableStyles.num : undefined}>
              {c.name}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.rows.map((r, i) => (
          <tr key={i}>
            {data.columns.map((c, j) => (
              <td key={c.key} className={c.role === "metric" ? tableStyles.num : undefined}>
                {c.role === "metric" ? formatValue(r[j], c.format, locale) : String(r[j] ?? "—")}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

export function WidgetBody({
  viz,
  data,
  settings,
  title,
  tableView,
  onChart,
}: {
  viz: string;
  data: ChartData;
  settings?: ChartSettings;
  title: string;
  tableView?: boolean;
  onChart?: (h: EChartHandle) => void;
}) {
  const { t, locale } = useI18n();
  const build = useCallback(
    (theme: ChartTheme) => buildOption(viz as Viz, data, settings ?? {}, locale, theme),
    [viz, data, settings, locale],
  );
  if (!data.rows.length) return <div className={s.center}>{t("bi.noData")}</div>;
  if (viz === "kpi") {
    const m = data.columns.findIndex((c) => c.role === "metric");
    const col = data.columns[m];
    return (
      <div className={s.kpi}>
        <div className={s.kpiValue}>{formatValue(data.rows[0][m], col?.format ?? "", locale)}</div>
      </div>
    );
  }
  if (viz === "table" || tableView) return <DataTable data={data} />;
  return <EChart build={build} label={title} onReady={onChart} />;
}
