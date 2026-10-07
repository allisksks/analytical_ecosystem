import { Plus, Trash2 } from "lucide-react";
import { useDeferredValue, useMemo, useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { PageBody } from "../../layout/AppShell";
import { useI18n, type TKey } from "../../shared/i18n";
import { formatNumber } from "../../shared/lib/format";
import {
  Button,
  Card,
  Checkbox,
  EmptyState,
  Field,
  IconButton,
  Input,
  PageHeader,
  PageSpinner,
  Select,
  Table,
  Textarea,
  useToast,
} from "../../shared/ui";
import { useSources } from "../data/api";
import { useProject } from "../projects/ProjectProvider";
import {
  useAbMutations,
  useBaseline,
  useExperiment,
  usePower,
  useTemplates,
  type Experiment,
  type ExperimentIn,
  type MetricTemplate,
} from "./api";
import { formatValue } from "./abStyle";
import s from "./ab.module.css";

const SEGMENTS = ["platform", "country", "source"] as const;
type Form = Omit<ExperimentIn, "project_id">;

const slug = (v: string) =>
  v
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 60);

function templateFor(templates: MetricTemplate[], semanticKey: string | null): MetricTemplate | undefined {
  if (!semanticKey) return undefined;
  return templates.find((m) => m.key === semanticKey || m.semantic_keys.includes(semanticKey));
}

export function DesignerPage() {
  const { id } = useParams();
  const { t } = useI18n();
  const { project } = useProject();
  const templates = useTemplates();
  const sources = useSources();
  const existing = useExperiment(id);
  const [params] = useSearchParams();
  if (!project)
    return (
      <PageBody>
        <EmptyState title={t("projects.none")} />
      </PageBody>
    );
  if (!templates.data || sources.isPending || (id && !existing.data)) return <PageSpinner />;
  const exp = existing.data;
  const metric = templateFor(templates.data, params.get("metric")) ?? templates.data[0];
  const event = params.get("event") ?? "";
  const initial: Form = exp
    ? toForm(exp)
    : {
        key: event ? `${event}_${metric.key}`.slice(0, 60) : "",
        name: "",
        hypothesis: "",
        description: "",
        owner: "",
        metric_key: metric.key,
        secondary_metrics: [],
        variants: [
          { key: "A", name: t("ab.res.control"), weight: 0.5, description: "" },
          { key: "B", name: "Test", weight: 0.5, description: "" },
        ],
        traffic_share: 1,
        segments: ["platform"],
        mde: 0.05,
        alpha: 0.05,
        power: 0.8,
        threshold: 0.95,
        event_name: event,
        splitter: "external",
        source_id: sources.data?.[0]?.id ?? null,
        assignments_table: "ab_assignments",
      };
  return <DesignerForm key={exp?.id ?? "new"} projectId={project.id} experimentId={exp?.id} initial={initial} />;
}

function toForm(e: Experiment): Form {
  return {
    key: e.key,
    name: e.name,
    hypothesis: e.hypothesis,
    description: e.description,
    owner: e.owner,
    metric_key: e.metric_key,
    secondary_metrics: e.secondary_metrics,
    variants: e.variants,
    traffic_share: e.traffic_share,
    segments: e.segments,
    mde: e.mde,
    alpha: e.alpha,
    power: e.power,
    baseline: e.baseline,
    planned_users: e.planned_users,
    planned_days: e.planned_days,
    threshold: e.threshold,
    event_name: e.event_name,
    splitter: e.splitter as Form["splitter"],
    source_id: e.source_id,
    assignments_table: e.assignments_table,
  };
}

function DesignerForm({
  projectId,
  experimentId,
  initial,
}: {
  projectId: string;
  experimentId?: string;
  initial: Form;
}) {
  const { t, locale } = useI18n();
  const toast = useToast();
  const navigate = useNavigate();
  const templates = useTemplates().data ?? [];
  const sources = useSources().data ?? [];
  const m = useAbMutations();
  const [form, setForm] = useState<Form>(initial);
  const [keyTouched, setKeyTouched] = useState(!!initial.key);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));
  const tpl = templates.find((x) => x.key === form.metric_key);
  const baseline = useBaseline(projectId, form.source_id, form.metric_key);
  const variants = form.variants ?? [];
  const weightSum = variants.reduce((a, v) => a + (v.weight ?? 0), 0) || 1;

  const powerInput = useMemo(() => {
    const b = baseline.data;
    const base = form.baseline ?? b?.baseline;
    if (!tpl || !base || base <= 0 || (tpl.type === "binary" && base >= 1)) return null;
    if (tpl.type === "continuous" && !b?.sd) return null;
    return {
      metric_type: tpl.type as "binary" | "continuous",
      baseline: base,
      mde: form.mde ?? 0.05,
      sd: tpl.type === "continuous" ? b?.sd : null,
      alpha: form.alpha ?? 0.05,
      power: form.power ?? 0.8,
      groups: variants.length,
      daily_users: b?.daily_users || null,
      traffic_share: form.traffic_share ?? 1,
    };
  }, [baseline.data, form.baseline, form.mde, form.alpha, form.power, form.traffic_share, tpl, variants.length]);
  const power = usePower(useDeferredValue(powerInput));

  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    const body: Form = {
      ...form,
      baseline: form.baseline ?? baseline.data?.baseline ?? null,
      planned_users: form.planned_users ?? power.data?.total ?? null,
      planned_days: form.planned_days ?? power.data?.days ?? null,
    };
    const done = (id: string, msg: TKey) => {
      toast.success(t(msg));
      navigate(`/ab/${id}`);
    };
    if (experimentId) {
      const { key: _key, ...patch } = body;
      void _key;
      m.patch.mutate(
        { id: experimentId, body: patch },
        { onSuccess: (r) => done(r.id, "ab.designer.saved"), onError: (e) => toast.error(e.message) },
      );
    } else {
      m.create.mutate(
        { ...body, project_id: projectId },
        { onSuccess: (r) => done(r.id, "ab.designer.created"), onError: (e) => toast.error(e.message) },
      );
    }
  };

  const updateVariant = (i: number, patch: Partial<(typeof variants)[number]>) =>
    set(
      "variants",
      variants.map((v, j) => (j === i ? { ...v, ...patch } : v)),
    );

  return (
    <PageBody>
      <PageHeader
        crumbs={[t("ab.title"), t("ab.list")]}
        title={experimentId ? form.name : t("ab.newExperiment")}
        actions={
          <>
            <Button onClick={() => navigate(experimentId ? `/ab/${experimentId}` : "/ab")}>{t("common.cancel")}</Button>
            <Button
              variant="primary"
              type="submit"
              form="ab-designer"
              loading={m.create.isPending || m.patch.isPending}
            >
              {t("ab.designer.save")}
            </Button>
          </>
        }
      />
      <form id="ab-designer" className={s.stack} onSubmit={submit}>
        <Card title={t("ab.designer.hypothesisSection")}>
          <div className={s.stack}>
            <div className={s.grid2}>
              <Field label={t("ab.designer.name")} required>
                <Input
                  required
                  value={form.name}
                  onChange={(e) => {
                    set("name", e.target.value);
                    if (!keyTouched && !experimentId) set("key", slug(e.target.value));
                  }}
                />
              </Field>
              <Field label={t("ab.designer.key")} hint={t("ab.designer.keyHint")} required>
                <Input
                  mono
                  required
                  disabled={!!experimentId}
                  pattern="[a-z0-9][a-z0-9_.\-]*"
                  value={form.key}
                  onChange={(e) => {
                    setKeyTouched(true);
                    set("key", e.target.value);
                  }}
                />
              </Field>
            </div>
            <Field label={t("ab.designer.hypothesis")}>
              <Textarea
                rows={3}
                placeholder={t("ab.designer.hypothesisPh")}
                value={form.hypothesis ?? ""}
                onChange={(e) => set("hypothesis", e.target.value)}
              />
            </Field>
            <div className={s.grid2}>
              <Field label={t("ab.designer.owner")}>
                <Input value={form.owner ?? ""} onChange={(e) => set("owner", e.target.value)} />
              </Field>
              <Field label={t("ab.designer.event")}>
                <Input mono value={form.event_name ?? ""} onChange={(e) => set("event_name", e.target.value)} />
              </Field>
            </div>
          </div>
        </Card>

        <Card title={t("ab.designer.metricSection")}>
          <div className={s.stack}>
            <div className={s.grid2}>
              <Field label={t("ab.designer.primary")} hint={tpl?.description}>
                <Select value={form.metric_key} onChange={(e) => set("metric_key", e.target.value)}>
                  {templates.map((x) => (
                    <option key={x.key} value={x.key}>
                      {x.name} · {x.type}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t("ab.designer.secondary")}>
                <div className={s.checks}>
                  {templates
                    .filter((x) => x.key !== form.metric_key)
                    .map((x) => (
                      <Checkbox
                        key={x.key}
                        label={x.name}
                        checked={(form.secondary_metrics ?? []).includes(x.key)}
                        onChange={(e) =>
                          set(
                            "secondary_metrics",
                            e.target.checked
                              ? [...(form.secondary_metrics ?? []), x.key]
                              : (form.secondary_metrics ?? []).filter((k) => k !== x.key),
                          )
                        }
                      />
                    ))}
                </div>
              </Field>
            </div>
            <div className={s.grid3}>
              <Field
                label={t("ab.designer.baseline")}
                hint={
                  baseline.data
                    ? `${t("ab.designer.baselineHint")}: ${formatValue(baseline.data.baseline, tpl?.unit ?? "", locale)}`
                    : t("ab.designer.baselineHint")
                }
              >
                <Input
                  type="number"
                  step="any"
                  min={0}
                  placeholder={baseline.data ? String(+baseline.data.baseline.toFixed(4)) : ""}
                  value={form.baseline ?? ""}
                  onChange={(e) => set("baseline", e.target.value === "" ? null : Number(e.target.value))}
                />
              </Field>
              <Field label={t("ab.designer.mde")}>
                <Input
                  type="number"
                  step="any"
                  min={0.1}
                  value={+((form.mde ?? 0.05) * 100).toFixed(2)}
                  onChange={(e) => set("mde", Number(e.target.value) / 100)}
                />
              </Field>
              <Field label={t("ab.designer.threshold")}>
                <Select value={String(form.threshold)} onChange={(e) => set("threshold", Number(e.target.value))}>
                  {[0.9, 0.95, 0.975, 0.99].map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t("ab.designer.alpha")}>
                <Select value={String(form.alpha)} onChange={(e) => set("alpha", Number(e.target.value))}>
                  {[0.01, 0.05, 0.1].map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t("ab.designer.power")}>
                <Select value={String(form.power)} onChange={(e) => set("power", Number(e.target.value))}>
                  {[0.8, 0.9].map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t("ab.designer.plannedDays")}>
                <Input
                  type="number"
                  min={1}
                  placeholder={power.data?.days ? String(power.data.days) : ""}
                  value={form.planned_days ?? ""}
                  onChange={(e) => set("planned_days", e.target.value === "" ? null : Number(e.target.value))}
                />
              </Field>
            </div>
            {power.data && (
              <div className={s.estimate} aria-live="polite">
                <span className="muted">{t("ab.designer.estimate")}</span>
                <span>
                  <span className={s.estimateValue}>{formatNumber(power.data.per_group, locale)}</span>{" "}
                  {t("ab.designer.perGroup")}
                </span>
                <span>
                  <span className={s.estimateValue}>{formatNumber(power.data.total, locale)}</span>{" "}
                  {t("ab.designer.total")}
                </span>
                {power.data.days && <strong>{t("ab.designer.days", { n: power.data.days })}</strong>}
              </div>
            )}
          </div>
        </Card>

        <Card
          title={t("ab.designer.variantsSection")}
          actions={
            variants.length < 6 && (
              <Button
                size="sm"
                variant="ghost"
                icon={<Plus size={14} />}
                onClick={() =>
                  set("variants", [
                    ...variants,
                    {
                      key: String.fromCharCode(65 + variants.length),
                      name: "",
                      weight: 1 / variants.length,
                      description: "",
                    },
                  ])
                }
              >
                {t("ab.designer.addVariant")}
              </Button>
            )
          }
        >
          <Table compact className={s.variantsTable}>
            <thead>
              <tr>
                <th style={{ width: 90 }}>{t("ab.designer.variant")}</th>
                <th>{t("ab.designer.variantName")}</th>
                <th>{t("ab.designer.description")}</th>
                <th style={{ width: 110 }}>{t("ab.designer.weight")}</th>
                <th style={{ width: 40 }} />
              </tr>
            </thead>
            <tbody>
              {variants.map((v, i) => (
                <tr key={i}>
                  <td>
                    <Input
                      mono
                      required
                      aria-label={t("ab.designer.variant")}
                      value={v.key}
                      onChange={(e) => updateVariant(i, { key: e.target.value })}
                    />
                  </td>
                  <td>
                    <Input
                      aria-label={t("ab.designer.variantName")}
                      value={v.name ?? ""}
                      onChange={(e) => updateVariant(i, { name: e.target.value })}
                    />
                  </td>
                  <td>
                    <Input
                      aria-label={t("ab.designer.description")}
                      value={v.description ?? ""}
                      onChange={(e) => updateVariant(i, { description: e.target.value })}
                    />
                  </td>
                  <td>
                    <Input
                      type="number"
                      min={1}
                      max={100}
                      aria-label={t("ab.designer.weight")}
                      value={Math.round(((v.weight ?? 0) / weightSum) * 100)}
                      onChange={(e) => updateVariant(i, { weight: Math.max(Number(e.target.value), 1) / 100 })}
                    />
                  </td>
                  <td>
                    {variants.length > 2 && (
                      <IconButton
                        label={t("common.delete")}
                        variant="ghost"
                        onClick={() =>
                          set(
                            "variants",
                            variants.filter((_, j) => j !== i),
                          )
                        }
                      >
                        <Trash2 size={14} />
                      </IconButton>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
          <div style={{ padding: "12px 16px" }}>
            <Field label={t("ab.designer.traffic")} hint={t("ab.designer.trafficHint")}>
              <Input
                type="number"
                min={1}
                max={100}
                style={{ maxWidth: 120 }}
                value={Math.round((form.traffic_share ?? 1) * 100)}
                onChange={(e) => set("traffic_share", Math.min(Math.max(Number(e.target.value), 1), 100) / 100)}
              />
            </Field>
          </div>
        </Card>

        <Card title={t("ab.designer.dataSection")}>
          <div className={s.stack}>
            <div className={s.grid3}>
              <Field label={t("ab.designer.splitter")}>
                <Select value={form.splitter} onChange={(e) => set("splitter", e.target.value as Form["splitter"])}>
                  {(["external", "internal"] as const).map((k) => (
                    <option key={k} value={k}>
                      {t(`ab.designer.splitters.${k}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t("ab.designer.source")}>
                <Select value={form.source_id ?? ""} onChange={(e) => set("source_id", e.target.value || null)}>
                  <option value="">—</option>
                  {sources.map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t("ab.designer.table")}>
                <Input
                  mono
                  value={form.assignments_table ?? ""}
                  onChange={(e) => set("assignments_table", e.target.value)}
                />
              </Field>
            </div>
            <Field label={t("ab.designer.segments")}>
              <div className={s.checks}>
                {SEGMENTS.map((k) => (
                  <Checkbox
                    key={k}
                    label={k}
                    checked={(form.segments ?? []).includes(k)}
                    onChange={(e) =>
                      set(
                        "segments",
                        e.target.checked ? [...(form.segments ?? []), k] : (form.segments ?? []).filter((x) => x !== k),
                      )
                    }
                  />
                ))}
              </div>
            </Field>
          </div>
        </Card>
      </form>
    </PageBody>
  );
}
