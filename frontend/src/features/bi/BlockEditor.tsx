import { Eye } from "lucide-react";
import { useMemo, useState } from "react";
import type { ChartData } from "../../shared/charts/buildOption";
import type { Schemas, WidgetOut } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import {
  Button,
  Checkbox,
  ErrorBox,
  Field,
  Input,
  Modal,
  Select,
  Skeleton,
  SqlEditor,
  Switch,
  Textarea,
  useToast,
} from "../../shared/ui";
import { useCan } from "../auth/AuthProvider";
import { useSources } from "../data/api";
import { useBiMutations, useDimensions, useMetrics, type GlobalFilters } from "./api";
import { WidgetBody } from "./WidgetBody";
import s from "./bi.module.css";

type Viz = Schemas["WidgetIn"]["viz"];
const VIZ: Viz[] = ["line", "bar", "area", "heatmap", "table", "kpi"];

export function BlockEditor({
  dashId,
  projectId,
  widget,
  filters,
  onClose,
}: {
  dashId: string;
  projectId: string | null;
  widget: WidgetOut | null;
  filters: GlobalFilters;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const can = useCan();
  const metrics = useMetrics();
  const dims = useDimensions();
  const sources = useSources();
  const m = useBiMutations();
  const spec = (widget?.spec ?? {}) as Record<string, unknown>;
  const [title, setTitle] = useState(widget?.title ?? "");
  const [viz, setViz] = useState<Viz>((widget?.viz as Viz) ?? "line");
  const [mode, setMode] = useState<"semantic" | "sql">((widget?.mode as "semantic" | "sql") ?? "semantic");
  const [metricKeys, setMetricKeys] = useState<string[]>((spec.metrics as string[]) ?? []);
  const [dimKeys, setDimKeys] = useState<string[]>((spec.dimensions as string[]) ?? []);
  const [grain, setGrain] = useState<string>((spec.grain as string) ?? "day");
  const [sourceId, setSourceId] = useState<string>((spec.source_id as string) ?? "");
  const [sql, setSql] = useState<string>(
    (spec.sql as string) ??
      "SELECT\n  install_date,\n  count(*) AS installs\nFROM users\nWHERE install_date BETWEEN {{date_from}} AND {{date_to}}\nGROUP BY 1\nORDER BY 1",
  );
  const [stacked, setStacked] = useState<boolean>(Boolean((widget?.settings as { stacked?: boolean })?.stacked));
  const [observation, setObservation] = useState(widget?.observation ?? "");
  const [preview, setPreview] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canSql = can("sql:run", projectId) || can("sql:run_all");

  const currentSpec = useMemo(
    () =>
      mode === "sql"
        ? { source_id: sourceId || sources.data?.[0]?.id, sql }
        : { metrics: metricKeys, dimensions: dimKeys, grain: viz === "kpi" ? "none" : grain },
    [mode, sourceId, sources.data, sql, metricKeys, dimKeys, grain, viz],
  );

  const runPreview = async () => {
    setError(null);
    try {
      const res = await m.preview.mutateAsync({ project_id: projectId, mode, spec: currentSpec, ...filters });
      setPreview(res as unknown as ChartData);
    } catch (e) {
      setPreview(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const save = async () => {
    setError(null);
    const body = {
      title: title || metricKeys.join(", ") || "SQL",
      viz,
      mode,
      spec: currentSpec,
      settings: { stacked },
      observation,
    };
    try {
      if (widget) await m.updateWidget.mutateAsync({ id: widget.id, dashId, body });
      else
        await m.addWidget.mutateAsync({
          dashId,
          body: { ...body, layout: { x: 0, y: 1000, w: viz === "kpi" ? 3 : 6, h: viz === "kpi" ? 2 : 4 } },
        });
      toast.success(t("admin.saved"));
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const toggle = (list: string[], key: string, set: (v: string[]) => void, max = 20) =>
    set(list.includes(key) ? list.filter((x) => x !== key) : [...list, key].slice(-max));

  return (
    <Modal
      open
      size="xl"
      title={widget ? t("bi.editBlock") : t("bi.addBlock")}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button icon={<Eye size={16} />} onClick={() => void runPreview()} loading={m.preview.isPending}>
            {t("bi.preview")}
          </Button>
          <Button
            variant="primary"
            onClick={() => void save()}
            loading={m.addWidget.isPending || m.updateWidget.isPending}
            disabled={mode === "semantic" ? metricKeys.length === 0 : !sql}
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className={s.editor}>
        <div style={{ display: "grid", gap: 14, alignContent: "start" }}>
          <Field label={t("bi.title")}>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label={t("bi.viz")}>
            <Select value={viz} onChange={(e) => setViz(e.target.value as Viz)}>
              {VIZ.map((v) => (
                <option key={v} value={v}>
                  {t(`bi.viz${v[0].toUpperCase()}${v.slice(1)}` as "bi.vizLine")}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("bi.dataMode")}>
            <Select value={mode} onChange={(e) => setMode(e.target.value as "semantic" | "sql")}>
              <option value="semantic">{t("bi.modeSemantic")}</option>
              <option value="sql" disabled={!canSql}>
                {t("bi.modeSql")}
              </option>
            </Select>
          </Field>
          {mode === "semantic" ? (
            <>
              <Field label={`${t("bi.metrics")} · ${metricKeys.length}`}>
                <div className={s.metricList}>
                  {metrics.data?.map((mt) => (
                    <Checkbox
                      key={mt.key}
                      label={<span title={mt.description}>{mt.name}</span>}
                      checked={metricKeys.includes(mt.key)}
                      onChange={() => toggle(metricKeys, mt.key, setMetricKeys)}
                    />
                  ))}
                </div>
              </Field>
              {viz !== "kpi" && (
                <>
                  <Field label={t("bi.dimensions")}>
                    <div className={s.metricList} style={{ maxHeight: 140 }}>
                      {dims.data?.map((d) => (
                        <Checkbox
                          key={d.key}
                          label={d.name}
                          checked={dimKeys.includes(d.key)}
                          onChange={() => toggle(dimKeys, d.key, setDimKeys, 2)}
                        />
                      ))}
                    </div>
                  </Field>
                  <Field label={t("bi.grain")}>
                    <Select value={grain} onChange={(e) => setGrain(e.target.value)}>
                      <option value="none">{t("bi.grainNone")}</option>
                      <option value="day">{t("bi.grainDay")}</option>
                      <option value="week">{t("bi.grainWeek")}</option>
                      <option value="month">{t("bi.grainMonth")}</option>
                    </Select>
                  </Field>
                </>
              )}
            </>
          ) : (
            <Field label={t("data.pickSource")}>
              <Select value={sourceId || sources.data?.[0]?.id || ""} onChange={(e) => setSourceId(e.target.value)}>
                {sources.data?.map((src) => (
                  <option key={src.id} value={src.id}>
                    {src.name}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          {(viz === "bar" || viz === "area") && (
            <Switch checked={stacked} onChange={setStacked} label={t("bi.stacked")} />
          )}
        </div>
        <div style={{ display: "grid", gap: 14, alignContent: "start", minWidth: 0 }}>
          {mode === "sql" && (
            <Field label="SQL" hint={t("bi.sqlPlaceholders")}>
              <SqlEditor value={sql} onChange={setSql} onRun={() => void runPreview()} minHeight={160} />
            </Field>
          )}
          {error && <ErrorBox>{error}</ErrorBox>}
          <div className={s.previewBox}>
            {m.preview.isPending ? (
              <Skeleton height={300} />
            ) : preview ? (
              <WidgetBody viz={viz} data={preview} settings={{ stacked }} title={title} />
            ) : (
              <div className={s.center}>{t("bi.preview")}</div>
            )}
          </div>
          <Field label={t("bi.observation")}>
            <Textarea
              value={observation}
              placeholder={t("bi.observationPlaceholder")}
              onChange={(e) => setObservation(e.target.value)}
            />
          </Field>
        </div>
      </div>
    </Modal>
  );
}
