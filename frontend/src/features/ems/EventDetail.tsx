import { BarChart3, Check, FlaskConical, GitCompare, Pencil, X } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import type { EmsEvent, EmsVersion, ParamIn } from "../../shared/api/types";
import { api } from "../../shared/api/client";
import { buildOption } from "../../shared/charts/buildOption";
import { EChart } from "../../shared/charts/EChart";
import type { ChartTheme } from "../../shared/charts/theme";
import { useI18n, type TKey } from "../../shared/i18n";
import { formatDateTime } from "../../shared/lib/format";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  Input,
  Modal,
  PageSpinner,
  Table,
  Tabs,
  Textarea,
  useToast,
} from "../../shared/ui";
import { useCan } from "../auth/AuthProvider";
import { useMetrics } from "../bi/api";
import { useEmsMutations, useEvent, useEventStats, useGlobalParams } from "./api";
import { HEALTH_TONE, STATUS_TONE } from "./emsStyle";
import { ParamsEditor } from "./ParamsEditor";
import s from "./ems.module.css";

type Tab = "params" | "metrics" | "versions" | "monitoring" | "discussion";

export function EventDetail({ id, projectId }: { id: string; projectId: string }) {
  const { t } = useI18n();
  const ev = useEvent(id);
  const [tab, setTab] = useState<Tab>("params");
  if (ev.isPending) return <PageSpinner />;
  if (!ev.data)
    return (
      <Card>
        <EmptyState title={ev.error?.message ?? "—"} />
      </Card>
    );
  const e = ev.data;
  return (
    <Card>
      <Header ev={e} projectId={projectId} />
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        items={(["params", "metrics", "versions", "monitoring", "discussion"] as Tab[]).map((k) => ({
          key: k,
          label: t(`ems.tabs.${k}` as TKey),
          count: k === "versions" ? e.versions.length : k === "discussion" ? e.comments.length : undefined,
        }))}
      />
      <div style={{ paddingTop: 12 }}>
        {tab === "params" && <ParamsTab ev={e} />}
        {tab === "metrics" && <MetricsTab ev={e} />}
        {tab === "versions" && <VersionsTab ev={e} />}
        {tab === "monitoring" && <Monitoring id={e.id} />}
        {tab === "discussion" && <Discussion ev={e} />}
      </div>
    </Card>
  );
}

function Header({ ev, projectId }: { ev: EmsEvent; projectId: string }) {
  const { t } = useI18n();
  const can = useCan();
  const toast = useToast();
  const m = useEmsMutations();
  const canApprove = can("events:approve", projectId);
  const setStatus = (status: "active" | "deprecated" | "archived") =>
    m.status.mutate({ id: ev.id, status }, { onError: (e) => toast.error(e.message) });
  const pending = ev.versions.find((v) => v.status === "pending");
  return (
    <>
      <div className={s.detailHead}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className={s.detailName}>{ev.name}</div>
          <div className={s.chips}>
            {ev.current_version && (
              <Badge mono tone="info">
                v{ev.current_version}
              </Badge>
            )}
            <Badge tone={STATUS_TONE[ev.status]}>{t(`ems.statuses.${ev.status}` as TKey)}</Badge>
            <Badge tone={HEALTH_TONE[ev.health]} dot>
              {t(`ems.healths.${ev.health}` as TKey)}
            </Badge>
            {ev.owner && <Badge mono>owner {ev.owner}</Badge>}
            {ev.category && <Badge>{ev.category}</Badge>}
          </div>
          <p className="muted" style={{ marginTop: 8 }}>
            {ev.description}
          </p>
        </div>
        {canApprove && ev.status === "active" && (
          <Button size="sm" variant="ghost" onClick={() => setStatus("deprecated")}>
            {t("ems.deprecate")}
          </Button>
        )}
        {canApprove && ev.status === "deprecated" && (
          <>
            <Button size="sm" variant="ghost" onClick={() => setStatus("active")}>
              {t("ems.restore")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setStatus("archived")}>
              {t("ems.archive")}
            </Button>
          </>
        )}
      </div>
      {pending && (
        <div className={s.pending}>
          <strong>
            {t("ems.pending")}: v{pending.version}
          </strong>
          <span>{pending.changelog}</span>
          <span className="muted">— {pending.author}</span>
          {canApprove && <ReviewButtons ev={ev} version={pending} />}
        </div>
      )}
    </>
  );
}

function ReviewButtons({ ev, version }: { ev: EmsEvent; version: EmsVersion }) {
  const { t } = useI18n();
  const toast = useToast();
  const m = useEmsMutations();
  const act = (approve: boolean) =>
    m.review.mutate(
      { id: ev.id, versionId: version.id, approve, comment: "" },
      { onError: (e) => toast.error(e.message) },
    );
  return (
    <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
      <Button
        size="sm"
        variant="primary"
        icon={<Check size={14} />}
        onClick={() => act(true)}
        loading={m.review.isPending}
      >
        {t("ems.approve")}
      </Button>
      <Button size="sm" icon={<X size={14} />} onClick={() => act(false)}>
        {t("ems.reject")}
      </Button>
    </span>
  );
}

function ParamTable({ params }: { params: ParamIn[] }) {
  const { t } = useI18n();
  return (
    <Table compact>
      <thead>
        <tr>
          <th>{t("ems.param")}</th>
          <th>{t("ems.type")}</th>
          <th>{t("ems.required")}</th>
          <th>{t("common.description")}</th>
        </tr>
      </thead>
      <tbody>
        {params.map((p) => (
          <tr key={p.name}>
            <td>
              <code>{p.name}</code>
            </td>
            <td>
              <Badge tone={p.type === "enum" ? "warn" : p.type === "timestamp" ? "info" : "neutral"} mono>
                {p.type}
              </Badge>
            </td>
            <td>{p.required ? <Badge tone="neg">required</Badge> : ""}</td>
            <td className="muted">
              {p.type === "enum" ? `${(p.enum ?? []).join(" | ")} ` : ""}
              {p.description}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function ParamsTab({ ev }: { ev: EmsEvent }) {
  const { t } = useI18n();
  const can = useCan();
  const globals = useGlobalParams();
  const [editing, setEditing] = useState(false);
  const current = ev.versions.find((v) => v.version === ev.current_version) ?? ev.versions[0];
  return (
    <>
      <div className={s.sectionTitle}>
        {t("ems.globalInherited")} · {globals.data?.length ?? 0}
      </div>
      <ParamTable params={(globals.data ?? []) as ParamIn[]} />
      <div className={s.sectionTitle} style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {t("ems.ownParams")} · {current?.params.length ?? 0}
        {can("events:edit", ev.project_id) && ev.status !== "archived" && (
          <Button size="sm" icon={<Pencil size={13} />} onClick={() => setEditing(true)} style={{ marginLeft: "auto" }}>
            {t("ems.proposeVersion")}
          </Button>
        )}
      </div>
      <ParamTable params={(current?.params ?? []) as ParamIn[]} />
      {editing && current && <ProposeDialog ev={ev} base={current} onClose={() => setEditing(false)} />}
    </>
  );
}

function ProposeDialog({ ev, base, onClose }: { ev: EmsEvent; base: EmsVersion; onClose: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const m = useEmsMutations();
  const [params, setParams] = useState<ParamIn[]>(base.params as ParamIn[]);
  const [changelog, setChangelog] = useState("");
  const [appVersion, setAppVersion] = useState("");
  const [description, setDescription] = useState(base.description);
  return (
    <Modal
      open
      size="xl"
      title={`${ev.name} · ${t("ems.proposeVersion")}`}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            variant="primary"
            loading={m.propose.isPending}
            onClick={() =>
              m.propose.mutate(
                { id: ev.id, body: { params, changelog, app_version: appVersion, description } },
                {
                  onSuccess: (v) => {
                    toast.success(`v${v.version}`);
                    onClose();
                  },
                },
              )
            }
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      {m.propose.error && <ErrorBox>{m.propose.error.message}</ErrorBox>}
      <div style={{ display: "grid", gap: 14 }}>
        <Field label={t("common.description")}>
          <Input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <ParamsEditor value={params} onChange={setParams} />
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12 }}>
          <Field label={t("ems.changelog")}>
            <Input value={changelog} onChange={(e) => setChangelog(e.target.value)} />
          </Field>
          <Field label={t("ems.appVersion")}>
            <Input value={appVersion} placeholder="1.9.0" onChange={(e) => setAppVersion(e.target.value)} />
          </Field>
        </div>
      </div>
    </Modal>
  );
}

function MetricsTab({ ev }: { ev: EmsEvent }) {
  const { t } = useI18n();
  const can = useCan();
  const toast = useToast();
  const navigate = useNavigate();
  const metrics = useMetrics();
  const m = useEmsMutations();
  const [goal, setGoal] = useState(ev.goal);
  const [question, setQuestion] = useState(ev.question);
  const editable = can("events:edit", ev.project_id);
  const linked = (metrics.data ?? []).filter((x) => ev.metric_keys.includes(x.key));
  const save = (body: { goal?: string; question?: string; metric_keys?: string[] }) =>
    m.patch.mutate({ id: ev.id, body }, { onError: (e) => toast.error(e.message) });
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <Field label={t("ems.goal")}>
        <Textarea
          value={goal}
          disabled={!editable}
          onChange={(e) => setGoal(e.target.value)}
          onBlur={() => goal !== ev.goal && save({ goal })}
          style={{ minHeight: 50 }}
        />
      </Field>
      <Field label={t("ems.question")}>
        <Textarea
          value={question}
          disabled={!editable}
          onChange={(e) => setQuestion(e.target.value)}
          onBlur={() => question !== ev.question && save({ question })}
          style={{ minHeight: 50 }}
        />
      </Field>
      <div className={s.sectionTitle}>{t("ems.linkedMetrics")}</div>
      <Table compact>
        <tbody>
          {linked.map((mt) => (
            <tr key={mt.key}>
              <td>
                <strong>{mt.name}</strong>
                <div className="muted" style={{ fontSize: 12 }}>
                  {mt.description}
                </div>
              </td>
              <td>
                <code style={{ fontSize: 12 }}>{mt.key}</code>
              </td>
              <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                <Button
                  size="sm"
                  icon={<FlaskConical size={14} />}
                  onClick={() => navigate(`/ab/new?metric=${mt.key}&event=${ev.name}`)}
                >
                  {t("ems.createAb")}
                </Button>{" "}
                <Button
                  size="sm"
                  icon={<BarChart3 size={14} />}
                  onClick={() => navigate(`/data/metrics?key=${mt.key}`)}
                >
                  {t("nav.bi")}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      {editable && (
        <Field label={t("ems.linkedMetrics")}>
          <select
            multiple
            aria-label={t("ems.linkedMetrics")}
            value={ev.metric_keys}
            onChange={(e) => save({ metric_keys: [...e.target.selectedOptions].map((o) => o.value) })}
            style={{
              minHeight: 120,
              border: "1px solid var(--field-border)",
              borderRadius: 6,
              background: "var(--field-bg)",
              padding: 6,
            }}
          >
            {metrics.data?.map((mt) => (
              <option key={mt.key} value={mt.key}>
                {mt.name}
              </option>
            ))}
          </select>
        </Field>
      )}
    </div>
  );
}

type DiffChange = { name: string; kind: string; fields?: string[] };

function VersionsTab({ ev }: { ev: EmsEvent }) {
  const { t, locale } = useI18n();
  const [pair, setPair] = useState<string[]>([]);
  const [diff, setDiff] = useState<{
    bump: string;
    changes: { name: string; kind: string; fields?: string[] }[];
  } | null>(null);
  const toggle = (v: string) => setPair((p) => (p.includes(v) ? p.filter((x) => x !== v) : [...p, v].slice(-2)));
  const compare = async () => {
    const [a, b] = [...pair].sort((x, y) => x.localeCompare(y, undefined, { numeric: true }));
    const { data } = await api.GET("/api/v1/ems/events/{event_id}/diff", {
      params: { path: { event_id: ev.id }, query: { from: a, to: b } },
    });
    setDiff(data ? { bump: data.bump, changes: data.changes as DiffChange[] } : null);
  };
  return (
    <>
      <Table compact>
        <tbody>
          {ev.versions.map((v) => (
            <tr key={v.id}>
              <td>
                <input
                  type="checkbox"
                  aria-label={`v${v.version}`}
                  checked={pair.includes(v.version)}
                  onChange={() => toggle(v.version)}
                />
              </td>
              <td>
                <Badge mono tone={v.status === "approved" ? "pos" : v.status === "pending" ? "warn" : "neg"}>
                  v{v.version}
                </Badge>
              </td>
              <td>
                {v.changelog}
                <div className="muted" style={{ fontSize: 12 }}>
                  {v.author}
                  {v.reviewed_by ? ` · ✓ ${v.reviewed_by}` : ""}
                </div>
              </td>
              <td className="muted">{v.app_version}</td>
              <td className="muted" style={{ whiteSpace: "nowrap" }}>
                {formatDateTime(v.created_at, locale)}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      <div style={{ marginTop: 10 }}>
        <Button size="sm" icon={<GitCompare size={14} />} disabled={pair.length !== 2} onClick={() => void compare()}>
          {t("ems.diff")}
        </Button>
      </div>
      {diff && (
        <div style={{ marginTop: 12 }}>
          <Badge tone="info">{t("ems.bump", { b: diff.bump })}</Badge>
          <ul>
            {diff.changes.map((c) => (
              <li
                key={c.name}
                className={c.kind === "added" ? s.diffAdded : c.kind === "removed" ? s.diffRemoved : s.diffChanged}
              >
                <code>{c.name}</code> — {t(`ems.${c.kind}` as TKey)}{" "}
                {c.fields?.length ? `(${c.fields.join(", ")})` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

function Monitoring({ id }: { id: string }) {
  const { t, locale } = useI18n();
  const stats = useEventStats(id, true);
  const data = useMemo(
    () => ({
      columns: [
        { key: "date", name: "Дата", role: "period", format: "" },
        { key: "platform", name: "Платформа", role: "dimension", format: "" },
        { key: "count", name: t("ems.lastDay"), role: "metric", format: "number" },
      ],
      rows: (stats.data ?? []).map((p) => [p.date, p.platform, p.count]),
    }),
    [stats.data, t],
  );
  const build = useCallback((theme: ChartTheme) => buildOption("line", data, {}, locale, theme), [data, locale]);
  if (stats.isPending) return <PageSpinner />;
  if (!stats.data?.length) return <EmptyState title={t("ems.notConfigured")} />;
  return (
    <>
      <div className={s.sectionTitle}>{t("ems.chartVolume")}</div>
      <div className={s.chart}>
        <EChart build={build} label={t("ems.chartVolume")} />
      </div>
    </>
  );
}

function Discussion({ ev }: { ev: EmsEvent }) {
  const { t, locale } = useI18n();
  const can = useCan();
  const m = useEmsMutations();
  const [text, setText] = useState("");
  return (
    <div>
      {ev.comments.map((c) => (
        <div key={c.id} style={{ padding: "8px 0", borderBottom: "1px solid var(--line-soft)" }}>
          <div className="muted" style={{ fontSize: 12 }}>
            {c.author} · {formatDateTime(c.created_at, locale)}
          </div>
          {c.text}
        </div>
      ))}
      {can("events:comment", ev.project_id) && (
        <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("kb.addComment")}
            style={{ minHeight: 60 }}
          />
          <Button
            size="sm"
            disabled={!text.trim()}
            onClick={() => m.comment.mutate({ id: ev.id, text }, { onSuccess: () => setText("") })}
          >
            {t("kb.send")}
          </Button>
        </div>
      )}
    </div>
  );
}
