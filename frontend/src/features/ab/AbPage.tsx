import clsx from "clsx";
import { FlaskConical, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { PageBody } from "../../layout/AppShell";
import { useI18n, type TKey } from "../../shared/i18n";
import { formatDate, formatPercent } from "../../shared/lib/format";
import { Badge, Button, Card, EmptyState, Input, PageHeader, PageSpinner, Table, Tabs } from "../../shared/ui";
import { useCan } from "../auth/AuthProvider";
import { useProject } from "../projects/ProjectProvider";
import { useExperiments, useTemplates, type ExpStatus, type ExperimentSummary } from "./api";
import { DECISION_TONE, REC_TONE, STATUS_TONE, formatLift, liftTone } from "./abStyle";
import s from "./ab.module.css";

type Filter = "all" | ExpStatus;
const FILTERS: Filter[] = ["all", "running", "review", "draft", "completed", "archived"];

export function ProbCell({ value }: { value: number | null | undefined }) {
  const { locale } = useI18n();
  if (value === null || value === undefined) return <span className="muted">—</span>;
  return (
    <span className={s.prob}>
      <span className={s.probBar}>
        <span className={s.probFill} style={{ width: `${value * 100}%` }} />
      </span>
      {formatPercent(value, locale, 1)}
    </span>
  );
}

function Progress({ e }: { e: ExperimentSummary }) {
  const { locale } = useI18n();
  const share = e.planned_users && e.users != null ? Math.min(e.users / e.planned_users, 1) : null;
  return (
    <div>
      <div className={s.bar}>
        <div
          className={clsx(s.barFill, e.status === "completed" && s.barDone)}
          style={{ width: `${(e.status === "completed" ? 1 : (share ?? 0)) * 100}%` }}
        />
      </div>
      <div className={s.sub}>
        {formatDate(e.started_at, locale)} → {e.ended_at ? formatDate(e.ended_at, locale) : "…"}
      </div>
    </div>
  );
}

export function AbPage() {
  const { t, locale } = useI18n();
  const can = useCan();
  const navigate = useNavigate();
  const { project } = useProject();
  const pid = project?.id;
  const experiments = useExperiments(pid);
  const templates = useTemplates();
  const [params, setParams] = useSearchParams();
  const filter = (params.get("status") as Filter | null) ?? "all";
  const [q, setQ] = useState("");
  const names = useMemo(() => Object.fromEntries((templates.data ?? []).map((m) => [m.key, m.name])), [templates.data]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: experiments.data?.length ?? 0 };
    for (const e of experiments.data ?? []) c[e.status] = (c[e.status] ?? 0) + 1;
    return c;
  }, [experiments.data]);
  const list = (experiments.data ?? []).filter(
    (e) =>
      (filter === "all" || e.status === filter) && (!q || `${e.name} ${e.key}`.toLowerCase().includes(q.toLowerCase())),
  );
  if (!project)
    return (
      <PageBody>
        <EmptyState title={t("projects.none")} />
      </PageBody>
    );
  const canCreate = can("experiments:propose", pid) || can("experiments:edit", pid);

  return (
    <PageBody wide>
      <PageHeader
        crumbs={[t("ab.title"), project.name]}
        title={t("ab.list")}
        actions={
          canCreate && (
            <Button variant="primary" icon={<Plus size={16} />} onClick={() => navigate("/ab/new")}>
              {t("ab.newExperiment")}
            </Button>
          )
        }
      />
      <Card padded={false}>
        <div className={s.toolbar}>
          <Tabs<Filter>
            variant="pills"
            value={filter}
            onChange={(k) => setParams(k === "all" ? {} : { status: k })}
            items={FILTERS.map((f) => ({
              key: f,
              label: f === "all" ? t("ab.all") : t(`ab.statuses.${f}` as TKey),
              count: counts[f] ?? 0,
            }))}
          />
          <Input className={s.search} placeholder={t("ab.search")} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {experiments.isPending ? (
          <PageSpinner />
        ) : !list.length ? (
          <EmptyState icon={<FlaskConical size={28} />} title={t("ab.empty")} />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>{t("ab.cols.experiment")}</th>
                <th>{t("ab.cols.metric")}</th>
                <th>{t("ab.cols.status")}</th>
                <th>{t("ab.cols.progress")}</th>
                <th className={s.num}>{t("ab.cols.probBest")}</th>
                <th className={s.num}>{t("ab.cols.lift")}</th>
                <th>{t("ab.cols.decision")}</th>
                <th>{t("ab.cols.owner")}</th>
              </tr>
            </thead>
            <tbody>
              {list.map((e) => (
                <tr key={e.id} className={s.row} onClick={() => navigate(`/ab/${e.id}`)}>
                  <td>
                    <strong>{e.name}</strong>
                    <div className={s.key}>{e.key}</div>
                  </td>
                  <td>
                    {names[e.metric_key] ?? e.metric_key}
                    <div className={s.sub}>{e.variants.map((v) => v.key).join(" / ")}</div>
                  </td>
                  <td>
                    <div className={s.chips}>
                      <Badge tone={STATUS_TONE[e.status]} dot={e.status === "running"}>
                        {t(`ab.statuses.${e.status}` as TKey)}
                      </Badge>
                      {e.srm_mismatch && <Badge tone="neg">SRM</Badge>}
                    </div>
                    {e.status === "running" && e.recommendation && (
                      <div className={s.sub}>
                        <Badge tone={REC_TONE[e.recommendation]}>
                          {t(`ab.recommendations.${e.recommendation}` as TKey)}
                        </Badge>
                      </div>
                    )}
                  </td>
                  <td>
                    <Progress e={e} />
                  </td>
                  <td className={s.num}>
                    <ProbCell value={e.prob_best} />
                  </td>
                  <td className={clsx(s.num, s[liftTone(e.lift)])}>{formatLift(e.lift, locale)}</td>
                  <td>
                    {e.decision ? (
                      <Badge tone={DECISION_TONE[e.decision]}>{t(`ab.decisions.${e.decision}` as TKey)}</Badge>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className={s.sub}>{e.owner}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </PageBody>
  );
}
