import clsx from "clsx";
import { BarChart3, Download, GripVertical, Image, Pencil, Settings2, Table2, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import type { EChartHandle } from "../../shared/charts/EChart";
import type { ChartData } from "../../shared/charts/buildOption";
import type { WidgetOut } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import { ErrorBox, IconButton, Skeleton, Textarea, useToast } from "../../shared/ui";
import { useBiMutations, useWidgetData, type GlobalFilters } from "./api";
import { downloadCsv, downloadDataUrl, slug } from "./download";
import { WidgetBody } from "./WidgetBody";
import s from "./bi.module.css";

export function WidgetCard({
  widget,
  dashId,
  filters,
  editing,
  canEdit,
  onConfigure,
  publicToken,
}: {
  widget: WidgetOut;
  dashId: string;
  filters: GlobalFilters;
  editing: boolean;
  canEdit: boolean;
  onConfigure?: () => void;
  publicToken?: string;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const m = useBiMutations();
  const rev = JSON.stringify([widget.spec, widget.mode]);
  const q = useWidgetData(dashId, widget.id, filters, rev, publicToken);
  const [tableView, setTableView] = useState(false);
  const [editObs, setEditObs] = useState(false);
  const [obs, setObs] = useState(widget.observation);
  const chart = useRef<EChartHandle | null>(null);
  const data = q.data as ChartData | undefined;

  const saveObs = () => {
    setEditObs(false);
    if (obs !== widget.observation)
      m.updateWidget.mutate(
        { id: widget.id, dashId, body: { observation: obs } },
        { onError: (e) => toast.error(e.message) },
      );
  };

  return (
    <div className={clsx(s.widget, editing && s.widgetEditing)}>
      <div className={s.widgetHead}>
        {editing && (
          <span className={clsx(s.dragHandle, "drag-handle")} aria-hidden>
            <GripVertical size={16} />
          </span>
        )}
        <h3 className={s.widgetTitle} title={widget.title}>
          {widget.title}
        </h3>
        {data && widget.viz !== "kpi" && widget.viz !== "table" && (
          <IconButton
            size="sm"
            label={tableView ? t("bi.chartView") : t("bi.tableView")}
            onClick={() => setTableView((v) => !v)}
          >
            {tableView ? <BarChart3 size={15} /> : <Table2 size={15} />}
          </IconButton>
        )}
        {data && !tableView && widget.viz !== "kpi" && widget.viz !== "table" && (
          <IconButton
            size="sm"
            label={t("bi.exportPng")}
            onClick={() => {
              const url = chart.current?.toDataURL();
              if (url) downloadDataUrl(url, `${slug(widget.title)}.svg`);
            }}
          >
            <Image size={15} />
          </IconButton>
        )}
        {data && (
          <IconButton
            size="sm"
            label={t("bi.exportCsv")}
            onClick={() => downloadCsv(data, `${slug(widget.title)}.csv`)}
          >
            <Download size={15} />
          </IconButton>
        )}
        {editing && (
          <>
            <IconButton size="sm" label={t("bi.editBlock")} onClick={onConfigure}>
              <Settings2 size={15} />
            </IconButton>
            <IconButton
              size="sm"
              label={t("bi.deleteBlock")}
              onClick={() =>
                m.deleteWidget.mutate({ id: widget.id, dashId }, { onError: (e) => toast.error(e.message) })
              }
            >
              <Trash2 size={15} />
            </IconButton>
          </>
        )}
      </div>
      <div className={s.widgetBody}>
        {q.isPending ? (
          <Skeleton height={120} />
        ) : q.error ? (
          <ErrorBox>{q.error.message}</ErrorBox>
        ) : data ? (
          <WidgetBody
            viz={widget.viz}
            data={data}
            settings={widget.settings}
            title={widget.title}
            tableView={tableView}
            onChart={(h) => (chart.current = h)}
          />
        ) : null}
      </div>
      {(widget.observation || canEdit) && widget.viz !== "kpi" && (
        <div className={s.observation}>
          {editObs ? (
            <Textarea
              className={s.observationEdit}
              autoFocus
              value={obs}
              placeholder={t("bi.observationPlaceholder")}
              onChange={(e) => setObs(e.target.value)}
              onBlur={saveObs}
            />
          ) : (
            <span>
              {widget.observation || <span className="muted">{t("bi.observationPlaceholder")}</span>}
              {widget.observation_author && <span className={s.observationMeta}>— {widget.observation_author}</span>}
              {canEdit && (
                <IconButton size="sm" label={t("bi.observation")} onClick={() => setEditObs(true)}>
                  <Pencil size={13} />
                </IconButton>
              )}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
