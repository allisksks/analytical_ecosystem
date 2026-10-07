import clsx from "clsx";
import {
  AlertTriangle,
  Archive,
  BookOpen,
  CheckCircle2,
  Download,
  Gavel,
  Pencil,
  Play,
  RefreshCw,
  Send,
  Sparkles,
  Square,
  Undo2,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { PageBody } from "../../layout/AppShell";
import { EChart } from "../../shared/charts/EChart";
import { downloadGet } from "../../shared/api/download";
import { useI18n, type TKey } from "../../shared/i18n";
import { formatDate, formatDateTime, formatNumber, formatPercent } from "../../shared/lib/format";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  KpiTile,
  Modal,
  PageHeader,
  PageSpinner,
  Select,
  Table,
  Textarea,
  useToast,
} from "../../shared/ui";
import { useAiStatus, useDraftExperiment } from "../ai/api";
import { useCan } from "../auth/AuthProvider";
import { ProbCell } from "./AbPage";
import { historyOption, posteriorOption } from "./abCharts";
import { DECISION_TONE, REC_TONE, STATUS_TONE, formatLift, formatValue, liftTone } from "./abStyle";
import {
  useAbMutations,
  useExperiment,
  useTemplates,
  type Comparison,
  type ExpStatus,
  type Experiment,
  type MetricResult,
} from "./api";
import s from "./ab.module.css";

type Decision = "ship" | "keep_control" | "inconclusive";

export function ExperimentPage() {
  const { id } = useParams();
  const { t } = useI18n();
  const exp = useExperiment(id);
  if (exp.isError)
    return (
      <PageBody>
        <ErrorBox title={t("common.notFound")}>{exp.error.message}</ErrorBox>
      </PageBody>
    );
  if (!exp.data) return <PageSpinner />;
  return <ExperimentView exp={exp.data} />;
}

function Banner({
  tone,
  icon,
  title,
  children,
}: {
  tone?: "neg" | "pos" | "warn";
  icon?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div
      role={tone === "neg" ? "alert" : "status"}
      className={clsx(
        s.banner,
        tone === "neg" && s.bannerNeg,
        tone === "pos" && s.bannerPos,
        tone === "warn" && s.bannerWarn,
      )}
    >
      {icon}
      <div>
        <div className={s.bannerTitle}>{title}</div>
        {children && <div>{children}</div>}
      </div>
    </div>
  );
}

function ExperimentView({ exp }: { exp: Experiment }) {
  const { t, locale } = useI18n();
  const can = useCan();
  const toast = useToast();
  const navigate = useNavigate();
  const m = useAbMutations();
  const templates = useTemplates();
  const [deciding, setDeciding] = useState(false);
  const pid = exp.project_id;
  const res = exp.result;
  const unit = res?.primary.unit ?? templates.data?.find((x) => x.key === exp.metric_key)?.unit ?? "";
  const fail = (e: Error) => toast.error(e.message);
  const go = (to: ExpStatus) => m.transition.mutate({ id: exp.id, to }, { onError: fail });

  const canPropose = can("experiments:propose", pid) || can("experiments:edit", pid);
  const canEdit = can("experiments:edit", pid);
  const canApprove = can("experiments:approve", pid);
  const actions: ReactNode[] = [];
  const btn = (key: string, label: TKey, icon: ReactNode, onClick: () => void, primary = false, loading = false) =>
    actions.push(
      <Button key={key} variant={primary ? "primary" : undefined} icon={icon} onClick={onClick} loading={loading}>
        {t(label)}
      </Button>,
    );
  if ((exp.status === "draft" || exp.status === "review") && canPropose)
    btn("edit", "ab.actions.edit", <Pencil size={16} />, () => navigate(`/ab/${exp.id}/edit`));
  if (exp.status === "draft" && canPropose)
    btn("submit", "ab.actions.submit", <Send size={16} />, () => go("review"), true, m.transition.isPending);
  if (exp.status === "draft" && canEdit)
    btn("archive", "ab.actions.archive", <Archive size={16} />, () => go("archived"));
  if (exp.status === "review" && canPropose) btn("back", "ab.actions.sendBack", <Undo2 size={16} />, () => go("draft"));
  if (exp.status === "review" && canApprove)
    btn("approve", "ab.actions.approve", <Play size={16} />, () => go("running"), true, m.transition.isPending);
  if ((exp.status === "running" || exp.status === "completed") && canEdit)
    btn(
      "recalc",
      "ab.actions.recalc",
      <RefreshCw size={16} />,
      () => m.recalculate.mutate(exp.id, { onError: fail }),
      false,
      m.recalculate.isPending,
    );
  if (exp.status === "running" && canEdit)
    btn("stop", "ab.actions.stop", <Square size={16} />, () => go("completed"), true, m.transition.isPending);
  if (exp.status === "completed" && canApprove)
    btn("decide", "ab.actions.decide", <Gavel size={16} />, () => setDeciding(true), !exp.decision);
  if (exp.status !== "draft" && exp.status !== "review" && exp.decision && !exp.kb_item_id && can("kb:write", pid))
    btn(
      "kb",
      "ab.actions.saveKb",
      <BookOpen size={16} />,
      () => m.saveToKb.mutate(exp.id, { onError: fail }),
      true,
      m.saveToKb.isPending,
    );
  if (exp.kb_item_id)
    actions.push(
      <Link key="kbl" to={`/kb/${exp.kb_item_id}`}>
        <Button icon={<BookOpen size={16} />}>{t("ab.actions.openKb")}</Button>
      </Link>,
    );
  if (exp.status === "completed" && canEdit)
    btn("arch2", "ab.actions.archive", <Archive size={16} />, () => go("archived"));
  btn(
    "report",
    "ab.actions.report",
    <Download size={16} />,
    () => void downloadGet(`/experiments/${exp.id}/report.md`, `${exp.key}.md`).catch(fail),
  );

  const control = res?.primary.variants[0];
  const best = res?.primary.comparisons.length
    ? res.primary.comparisons.reduce((a, b) => (b.prob_better > a.prob_better ? b : a))
    : undefined;
  const bestStat = res?.primary.variants.find((v) => v.key === best?.variant);
  const totalAssigned = res ? Object.values(res.assigned).reduce((a, b) => a + b, 0) : 0;

  return (
    <PageBody wide>
      <PageHeader
        crumbs={[
          <Link key="l" to="/ab">
            {t("ab.title")}
          </Link>,
          exp.key,
        ]}
        title={exp.name}
        subtitle={
          <span className={s.chips}>
            <Badge tone={STATUS_TONE[exp.status]} dot={exp.status === "running"}>
              {t(`ab.statuses.${exp.status}` as TKey)}
            </Badge>
            {exp.decision && (
              <Badge tone={DECISION_TONE[exp.decision]}>{t(`ab.decisions.${exp.decision}` as TKey)}</Badge>
            )}
            {exp.last_calculated_at && (
              <span className="muted">
                {t("ab.res.calculated", { date: formatDateTime(exp.last_calculated_at, locale) })}
              </span>
            )}
          </span>
        }
        actions={<>{actions}</>}
      />
      {exp.last_error && (
        <Banner
          tone="neg"
          icon={<AlertTriangle size={18} />}
          title={t("ab.res.lastError", { error: exp.last_error })}
        />
      )}
      {res?.srm.mismatch && (
        <Banner tone="neg" icon={<AlertTriangle size={18} />} title={t("ab.res.srmTitle")}>
          {t("ab.res.srmText", {
            obs: res.srm.observed.map((n) => formatNumber(n, locale)).join(" / "),
            exp: res.srm.expected.map((n) => formatNumber(n, locale)).join(" / "),
            p: res.srm.p_value.toExponential(2),
          })}
        </Banner>
      )}
      {exp.decision ? (
        <Banner
          tone={exp.decision === "ship" ? "pos" : exp.decision === "keep_control" ? "neg" : "warn"}
          icon={<CheckCircle2 size={18} />}
          title={`${t(`ab.decisions.${exp.decision}` as TKey)} · ${exp.decided_by}`}
        >
          {exp.conclusion}
        </Banner>
      ) : (
        res &&
        res.matured_users > 0 &&
        exp.status !== "draft" &&
        !res.srm.mismatch && (
          <Banner
            tone={
              REC_TONE[res.recommendation] === "pos"
                ? "pos"
                : REC_TONE[res.recommendation] === "neg"
                  ? "neg"
                  : undefined
            }
            title={t(`ab.recommendations.${res.recommendation}` as TKey)}
          >
            {t(`ab.recommendationText.${res.recommendation}` as TKey, { v: res.best_variant ?? "" })}
          </Banner>
        )
      )}

      {res && res.matured_users > 0 ? (
        <div className={s.stack}>
          <div className={s.kpis}>
            <KpiTile
              label={t("ab.res.assigned")}
              value={formatNumber(totalAssigned, locale)}
              hint={
                res.progress != null ? t("ab.res.progress", { p: formatPercent(res.progress, locale, 0) }) : undefined
              }
            />
            <KpiTile label={t("ab.res.matured")} value={formatNumber(res.matured_users, locale)} />
            <KpiTile
              label={`${t("ab.res.control")} (${control?.key})`}
              value={formatValue(control?.mean, unit, locale)}
            />
            {bestStat && (
              <KpiTile
                label={`${t("ab.res.best")} (${bestStat.key})`}
                value={formatValue(bestStat.mean, unit, locale)}
              />
            )}
            <KpiTile
              label={t("ab.res.lift")}
              value={formatLift(best?.lift, locale)}
              tone={liftTone(best?.lift)}
              hint={
                best ? `[${formatLift(best.lift_ci[0], locale)}; ${formatLift(best.lift_ci[1], locale)}]` : undefined
              }
            />
            <KpiTile
              label={t("ab.res.probBest")}
              value={best ? formatPercent(best.prob_better, locale, 1) : "—"}
              tone={
                best && best.prob_better >= exp.threshold
                  ? "pos"
                  : best && best.prob_better <= 1 - exp.threshold
                    ? "neg"
                    : "neutral"
              }
              hint={`${t("ab.designer.threshold")}: ${exp.threshold}`}
            />
          </div>
          <div className={s.grid2}>
            <Card title={t("ab.res.posterior")} subtitle={res.primary.name}>
              <EChart
                label={t("ab.res.posterior")}
                height={260}
                build={(theme) =>
                  posteriorOption(
                    [
                      {
                        key: res.primary.variants[0].key,
                        mean: res.primary.comparisons[0]?.posterior_control[0] ?? 0,
                        sd: res.primary.comparisons[0]?.posterior_control[1] ?? 0,
                      },
                      ...res.primary.comparisons.map((c) => ({
                        key: c.variant,
                        mean: c.posterior_variant[0],
                        sd: c.posterior_variant[1],
                      })),
                    ],
                    (v) => formatValue(v, unit, locale),
                    theme,
                  )
                }
              />
            </Card>
            <Card title={t("ab.res.history")}>
              {exp.history.length > 1 ? (
                <EChart
                  label={t("ab.res.history")}
                  height={260}
                  build={(theme) =>
                    historyOption(
                      exp.history.map((h) => ({ at: h.calculated_at, prob: h.prob_best })),
                      exp.threshold,
                      (d) => formatDateTime(d, locale),
                      theme,
                    )
                  }
                />
              ) : (
                <EmptyState
                  title={formatPercent(best?.prob_better, locale, 1)}
                  description={t("ab.res.calculated", { date: formatDateTime(exp.last_calculated_at, locale) })}
                />
              )}
            </Card>
          </div>
          <MetricCard title={t("ab.res.variants")} metric={res.primary} />
          {res.secondary.length > 0 && (
            <Card title={t("ab.res.secondary")} padded={false}>
              <CompactMetrics metrics={res.secondary} />
            </Card>
          )}
          <Card title={t("ab.res.segments")} padded={false}>
            {res.segments.length ? (
              <SegmentsTable exp={exp} unit={unit} />
            ) : (
              <EmptyState title={t("ab.res.noSegments")} />
            )}
          </Card>
          <DesignCard exp={exp} />
        </div>
      ) : (
        <div className={s.stack}>
          <Card>
            <EmptyState
              title={res ? t("ab.recommendations.collecting") : t("ab.res.noResults")}
              description={
                res
                  ? `${t("ab.res.assigned")}: ${formatNumber(totalAssigned, locale)} · ${t("ab.recommendationText.collecting")}`
                  : undefined
              }
            />
          </Card>
          <DesignCard exp={exp} />
        </div>
      )}
      {deciding && <DecisionDialog exp={exp} onClose={() => setDeciding(false)} />}
    </PageBody>
  );
}

function MetricCard({ title, metric }: { title: string; metric: MetricResult }) {
  const { t, locale } = useI18n();
  const comps = new Map<string, Comparison>(metric.comparisons.map((c) => [c.variant, c]));
  return (
    <Card title={title} subtitle={`${metric.name} · ${metric.comparisons[0]?.method ?? ""}`} padded={false}>
      <Table>
        <thead>
          <tr>
            <th>{t("ab.designer.variant")}</th>
            <th className={s.num}>{t("ab.res.users")}</th>
            <th className={s.num}>{t("ab.res.mean")}</th>
            <th className={s.num}>{t("ab.res.lift")}</th>
            <th className={s.num}>{t("ab.res.ci")}</th>
            <th className={s.num}>{t("ab.res.probBest")}</th>
            <th className={s.num}>{t("ab.res.loss")}</th>
            <th className={s.num}>{t("ab.res.pValue")}</th>
            <th>{t("ab.res.frequentist")}</th>
          </tr>
        </thead>
        <tbody>
          {metric.variants.map((v, i) => {
            const c = comps.get(v.key);
            return (
              <tr key={v.key}>
                <td>
                  <strong>{v.key}</strong> {i === 0 && <Badge>{t("ab.res.control")}</Badge>}
                </td>
                <td className={s.num}>{formatNumber(v.n, locale)}</td>
                <td className={s.num}>{formatValue(v.mean, metric.unit ?? "", locale)}</td>
                <td className={clsx(s.num, c && s[liftTone(c.lift)])}>{c ? formatLift(c.lift, locale) : "—"}</td>
                <td className={s.num}>
                  {c ? `${formatLift(c.lift_ci[0], locale)} … ${formatLift(c.lift_ci[1], locale)}` : "—"}
                </td>
                <td className={s.num}>{c ? <ProbCell value={c.prob_better} /> : "—"}</td>
                <td className={s.num}>{c ? formatPercent(c.expected_loss, locale, 2) : "—"}</td>
                <td className={s.num}>{c?.frequentist ? c.frequentist.p_value.toFixed(4) : "—"}</td>
                <td>
                  {c?.frequentist && (
                    <Badge tone={c.frequentist.significant ? "pos" : "neutral"} title={c.frequentist.method}>
                      {c.frequentist.significant ? t("ab.res.significant") : t("ab.res.notSignificant")}
                    </Badge>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </Table>
    </Card>
  );
}

function CompactMetrics({ metrics }: { metrics: MetricResult[] }) {
  const { t, locale } = useI18n();
  return (
    <Table compact>
      <thead>
        <tr>
          <th>{t("ab.cols.metric")}</th>
          <th>{t("ab.designer.variant")}</th>
          <th className={s.num}>{t("ab.res.mean")}</th>
          <th className={s.num}>{t("ab.res.lift")}</th>
          <th className={s.num}>{t("ab.res.probBest")}</th>
          <th className={s.num}>{t("ab.res.pValue")}</th>
        </tr>
      </thead>
      <tbody>
        {metrics.flatMap((m) =>
          m.variants.map((v, i) => {
            const c = m.comparisons.find((x) => x.variant === v.key);
            return (
              <tr key={`${m.metric}-${v.key}`}>
                <td>{i === 0 && <strong>{m.name}</strong>}</td>
                <td>{v.key}</td>
                <td className={s.num}>{formatValue(v.mean, m.unit ?? "", locale)}</td>
                <td className={clsx(s.num, c && s[liftTone(c.lift)])}>{c ? formatLift(c.lift, locale) : "—"}</td>
                <td className={s.num}>{c ? <ProbCell value={c.prob_better} /> : "—"}</td>
                <td className={s.num}>{c?.frequentist?.p_value.toFixed(4) ?? "—"}</td>
              </tr>
            );
          }),
        )}
      </tbody>
    </Table>
  );
}

function SegmentsTable({ exp, unit }: { exp: Experiment; unit: string }) {
  const { t, locale } = useI18n();
  const keys = exp.variants.map((v) => v.key);
  return (
    <Table compact>
      <thead>
        <tr>
          <th>{t("ab.res.segment")}</th>
          {keys.map((k) => (
            <th key={k} className={s.num}>
              {k}
            </th>
          ))}
          <th className={s.num}>{t("ab.res.lift")}</th>
          <th className={s.num}>{t("ab.res.probBest")}</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {exp.result!.segments.map((seg) => {
          const c = seg.comparisons.reduce<Comparison | undefined>(
            (a, b) => (!a || b.prob_better > a.prob_better ? b : a),
            undefined,
          );
          return (
            <tr key={`${seg.segment}=${seg.value}`}>
              <td>
                <span className="muted">{seg.segment}</span> = <strong>{seg.value}</strong>
              </td>
              {keys.map((k) => {
                const v = seg.variants.find((x) => x.key === k);
                return (
                  <td key={k} className={s.num}>
                    {formatValue(v?.mean, unit, locale)}
                    <div className={s.sub}>n = {formatNumber(v?.n, locale)}</div>
                  </td>
                );
              })}
              <td className={clsx(s.num, c && s[liftTone(c.lift)])}>{formatLift(c?.lift, locale)}</td>
              <td className={s.num}>
                <ProbCell value={c?.prob_better} />
              </td>
              <td>{seg.srm_mismatch && <Badge tone="neg">SRM</Badge>}</td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function DesignCard({ exp }: { exp: Experiment }) {
  const { t, locale } = useI18n();
  const templates = useTemplates().data ?? [];
  const name = (k: string) => templates.find((x) => x.key === k)?.name ?? k;
  const rows: [TKey, ReactNode][] = [
    ["ab.designer.hypothesis", exp.hypothesis || "—"],
    ["ab.designer.primary", name(exp.metric_key)],
    ["ab.designer.secondary", exp.secondary_metrics.map(name).join(", ") || "—"],
    [
      "ab.res.variants",
      exp.variants.map((v) => `${v.key} — ${v.name || v.key} (${formatPercent(v.weight, locale, 0)})`).join("; "),
    ],
    ["ab.designer.traffic", formatPercent(exp.traffic_share, locale, 0)],
    ["ab.designer.threshold", `${exp.threshold} · MDE ${formatPercent(exp.mde, locale, 1)} · α ${exp.alpha}`],
    ["ab.designer.plannedUsers", exp.planned_users ? formatNumber(exp.planned_users, locale) : "—"],
    [
      "ab.res.period",
      `${formatDate(exp.started_at, locale)} — ${exp.ended_at ? formatDate(exp.ended_at, locale) : "…"}`,
    ],
    ["ab.designer.splitter", `${t(`ab.designer.splitters.${exp.splitter}` as TKey)} · ${exp.assignments_table}`],
    ["ab.designer.segments", exp.segments.join(", ") || "—"],
    [
      "ab.designer.event",
      exp.event_name ? (
        <Link key="ev" to={`/ems?event=${exp.event_name}`}>
          {exp.event_name}
        </Link>
      ) : (
        "—"
      ),
    ],
    ["ab.designer.owner", exp.owner],
    ["ab.res.approvedBy", exp.approved_by || "—"],
  ];
  return (
    <Card title={t("ab.res.design")}>
      <dl className={s.dl}>
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{t(k)}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function DecisionDialog({ exp, onClose }: { exp: Experiment; onClose: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const m = useAbMutations();
  const rec = exp.result?.recommendation;
  const [decision, setDecision] = useState<Decision>(
    (exp.decision as Decision) || (rec === "ship" || rec === "keep_control" ? rec : "inconclusive"),
  );
  const [conclusion, setConclusion] = useState(exp.conclusion);
  const ai = useAiStatus();
  const draft = useDraftExperiment();
  return (
    <Modal
      open
      title={t("ab.decisionModal.title")}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            variant="primary"
            disabled={!conclusion.trim()}
            loading={m.decide.isPending}
            onClick={() =>
              m.decide.mutate(
                { id: exp.id, body: { decision, conclusion } },
                { onSuccess: onClose, onError: (e) => toast.error(e.message) },
              )
            }
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className={s.stack}>
        <Field label={t("ab.decisionModal.decision")}>
          <Select value={decision} onChange={(e) => setDecision(e.target.value as Decision)}>
            {(["ship", "keep_control", "inconclusive"] as const).map((d) => (
              <option key={d} value={d}>
                {t(`ab.decisions.${d}`)}
              </option>
            ))}
          </Select>
        </Field>
        {ai.data?.enabled && exp.result && (
          <div>
            <Button
              size="sm"
              icon={<Sparkles size={14} />}
              loading={draft.isPending}
              onClick={() =>
                draft.mutate(exp.id, {
                  onSuccess: (r) => setConclusion(r.text),
                  onError: (e) => toast.error(e.message),
                })
              }
            >
              {t("ai.draft")}
            </Button>
            {draft.data && (
              <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>
                {t("ai.draftHint")}
              </span>
            )}
          </div>
        )}
        <Field label={t("ab.decisionModal.conclusion")} required>
          <Textarea
            rows={5}
            placeholder={t("ab.decisionModal.conclusionPh")}
            value={conclusion}
            onChange={(e) => setConclusion(e.target.value)}
          />
        </Field>
      </div>
    </Modal>
  );
}
