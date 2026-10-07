import { Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { ChartData } from "../../shared/charts/buildOption";
import { useI18n } from "../../shared/i18n";
import {
  Button,
  Card,
  Checkbox,
  ErrorBox,
  Field,
  IconButton,
  Input,
  PageHeader,
  Select,
  Skeleton,
} from "../../shared/ui";
import { useProject } from "../projects/ProjectProvider";
import { useBiMutations, useDimensions, useDimensionValues, useMetrics } from "./api";
import { FilterBar, type FilterState } from "./FilterBar";
import { defaultFilters, toGlobal } from "./filters";
import { DataTable, WidgetBody } from "./WidgetBody";
import s from "./bi.module.css";

interface CohortDraft {
  label: string;
  dimension: string;
  values: string[];
  installFrom: string;
  installTo: string;
}

const emptyCohort = (label: string, values: string[] = []): CohortDraft => ({
  label,
  dimension: "app_version",
  values,
  installFrom: "",
  installTo: "",
});

/** Product scenario BP-2: compare cohorts of two releases without SQL and without an analyst. */
export function CohortsPage() {
  const { t } = useI18n();
  const { project } = useProject();
  const metrics = useMetrics();
  const m = useBiMutations();
  const [metric, setMetric] = useState("retention_curve");
  const [axis, setAxis] = useState<"day_n" | "week" | "day">("day_n");
  const [filters, setFilters] = useState<FilterState>(() => ({ ...defaultFilters(90), preset: 90 }));
  const [cohorts, setCohorts] = useState<CohortDraft[]>([
    emptyCohort("1.7.0", ["1.7.0"]),
    emptyCohort("1.8.0", ["1.8.0"]),
  ]);
  const [data, setData] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setError(null);
    const g = toGlobal(filters);
    try {
      const res = await m.semanticQuery.mutateAsync({
        project_id: project?.id ?? null,
        metrics: [metric],
        dimensions: axis === "day_n" ? ["day_n"] : [],
        grain: axis === "day_n" ? "none" : axis,
        date_from: g.date_from,
        date_to: g.date_to,
        filters: g.filters,
        limit: 5000,
        cohorts: cohorts.map((c) => ({
          label: c.label || "—",
          filters: [
            ...(c.values.length ? [{ dimension: c.dimension, op: "in" as const, values: c.values }] : []),
            ...(c.installFrom ? [{ dimension: "install_date", op: "gte" as const, values: [c.installFrom] }] : []),
            ...(c.installTo ? [{ dimension: "install_date", op: "lte" as const, values: [c.installTo] }] : []),
          ],
        })),
      });
      setData(res as unknown as ChartData);
    } catch (e) {
      setData(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <>
      <PageHeader crumbs={["BI", project?.name ?? ""]} title={t("bi.cohorts")} />
      <FilterBar value={filters} onChange={setFilters} projectId={project?.id ?? null} />
      <Card>
        <div
          style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 16, alignItems: "end", marginBottom: 16 }}
        >
          <Field label={t("bi.metrics")}>
            <Select value={metric} onChange={(e) => setMetric(e.target.value)}>
              {metrics.data?.map((mt) => (
                <option key={mt.key} value={mt.key}>
                  {mt.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("bi.compareBy")}>
            <Select value={axis} onChange={(e) => setAxis(e.target.value as typeof axis)}>
              <option value="day_n">День жизни (day_n)</option>
              <option value="day">{t("bi.grainDay")}</option>
              <option value="week">{t("bi.grainWeek")}</option>
            </Select>
          </Field>
          <Button
            variant="primary"
            icon={<Play size={16} />}
            onClick={() => void run()}
            loading={m.semanticQuery.isPending}
          >
            {t("bi.run")}
          </Button>
        </div>
        <div className={s.cohortGrid}>
          {cohorts.map((c, i) => (
            <CohortEditor
              key={i}
              index={i}
              cohort={c}
              projectId={project?.id ?? null}
              onChange={(next) => setCohorts(cohorts.map((x, j) => (j === i ? next : x)))}
              onRemove={cohorts.length > 2 ? () => setCohorts(cohorts.filter((_, j) => j !== i)) : undefined}
            />
          ))}
          {cohorts.length < 6 && (
            <Button
              icon={<Plus size={16} />}
              onClick={() => setCohorts([...cohorts, emptyCohort(`C${cohorts.length + 1}`)])}
            >
              {t("bi.addCohort")}
            </Button>
          )}
        </div>
      </Card>
      <div style={{ marginTop: 16 }}>
        {error && <ErrorBox>{error}</ErrorBox>}
        {m.semanticQuery.isPending && <Skeleton height={360} />}
        {data && !m.semanticQuery.isPending && (
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)", gap: 16 }}>
            <Card title={metrics.data?.find((x) => x.key === metric)?.name}>
              <div style={{ height: 380 }}>
                <WidgetBody viz="line" data={data} title={metric} />
              </div>
            </Card>
            <Card title={t("bi.tableView")} padded={false}>
              <div style={{ padding: 12 }}>
                <DataTable data={data} maxHeight={380} />
              </div>
            </Card>
          </div>
        )}
      </div>
    </>
  );
}

function CohortEditor({
  index,
  cohort,
  projectId,
  onChange,
  onRemove,
}: {
  index: number;
  cohort: CohortDraft;
  projectId: string | null;
  onChange: (c: CohortDraft) => void;
  onRemove?: () => void;
}) {
  const { t } = useI18n();
  const dims = useDimensions();
  const values = useDimensionValues(cohort.dimension, projectId);
  return (
    <div className={s.cohortCard}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className={s.swatch} style={{ background: `var(--chart-${index + 1})` }} aria-hidden />
        <Input
          aria-label={t("bi.cohortLabel")}
          value={cohort.label}
          onChange={(e) => onChange({ ...cohort, label: e.target.value })}
        />
        {onRemove && (
          <IconButton label={t("common.delete")} onClick={onRemove}>
            <Trash2 size={16} />
          </IconButton>
        )}
      </div>
      <Field label={t("bi.dimension")}>
        <Select
          value={cohort.dimension}
          onChange={(e) => onChange({ ...cohort, dimension: e.target.value, values: [] })}
        >
          {dims.data
            ?.filter((d) => d.key !== "day_n")
            .map((d) => (
              <option key={d.key} value={d.key}>
                {d.name}
              </option>
            ))}
        </Select>
      </Field>
      <Field label={t("bi.values")}>
        <div className={s.metricList} style={{ maxHeight: 120 }}>
          {(values.data ?? []).map((v) => {
            const val = String(v);
            return (
              <Checkbox
                key={val}
                label={val}
                checked={cohort.values.includes(val)}
                onChange={(e) =>
                  onChange({
                    ...cohort,
                    values: e.target.checked ? [...cohort.values, val] : cohort.values.filter((x) => x !== val),
                  })
                }
              />
            );
          })}
        </div>
      </Field>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <Field label={`install ${t("bi.from")}`}>
          <Input
            type="date"
            value={cohort.installFrom}
            onChange={(e) => onChange({ ...cohort, installFrom: e.target.value })}
          />
        </Field>
        <Field label={t("bi.to")}>
          <Input
            type="date"
            value={cohort.installTo}
            onChange={(e) => onChange({ ...cohort, installTo: e.target.value })}
          />
        </Field>
      </div>
    </div>
  );
}
