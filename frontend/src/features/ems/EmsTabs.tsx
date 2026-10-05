import { CheckCheck, Eye } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import type { ParamIn } from "../../shared/api/types";
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
  PageSpinner,
  Select,
  useToast,
} from "../../shared/ui";
import { useCan } from "../auth/AuthProvider";
import { useSources } from "../data/api";
import { useAlerts, useEmsMutations, useGlobalParams, useGovernance, useTracking } from "./api";
import { SEVERITY_TONE } from "./emsStyle";
import { ParamsEditor } from "./ParamsEditor";
import s from "./ems.module.css";

export function AlertsTab({ projectId }: { projectId: string }) {
  const { t, locale } = useI18n();
  const can = useCan();
  const [status, setStatus] = useState("active");
  const alerts = useAlerts(projectId, status);
  const m = useEmsMutations();
  return (
    <Card padded={false}>
      <div className={s.toolbar}>
        <Select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          style={{ maxWidth: 220 }}
          aria-label={t("common.status")}
        >
          <option value="active">open / acknowledged</option>
          <option value="resolved">resolved</option>
          <option value="all">all</option>
        </Select>
      </div>
      {alerts.isPending ? (
        <PageSpinner />
      ) : !alerts.data?.length ? (
        <EmptyState title={t("ems.noAlerts")} />
      ) : (
        alerts.data.map((a) => (
          <div key={a.id} className={s.alertCard}>
            <Badge tone={SEVERITY_TONE[a.severity]} dot>
              {a.severity}
            </Badge>
            <div>
              <div className={s.alertTitle}>{a.title}</div>
              <div>{a.message}</div>
              <div className={s.alertMeta}>
                {a.kind} · {formatDateTime(a.created_at, locale)} · {a.status}
                {a.acknowledged_by ? ` · ${a.acknowledged_by}` : ""}
                {a.event_name && (
                  <>
                    {" "}
                    · <Link to={`/ems?tab=registry&event=${a.event_name}`}>{a.event_name}</Link>
                  </>
                )}
              </div>
            </div>
            {can("events:edit", projectId) && a.status !== "resolved" && (
              <div style={{ display: "flex", gap: 6 }}>
                {a.status === "open" && (
                  <Button
                    size="sm"
                    icon={<Eye size={14} />}
                    onClick={() => m.alert.mutate({ id: a.id, action: "ack" })}
                  >
                    {t("ems.ack")}
                  </Button>
                )}
                <Button
                  size="sm"
                  icon={<CheckCheck size={14} />}
                  onClick={() => m.alert.mutate({ id: a.id, action: "resolve" })}
                >
                  {t("ems.resolve")}
                </Button>
              </div>
            )}
          </div>
        ))
      )}
    </Card>
  );
}

export function GovernanceTab({ projectId }: { projectId: string }) {
  const { t } = useI18n();
  const gov = useGovernance(projectId);
  if (gov.isPending) return <PageSpinner />;
  if (!gov.data) return null;
  const blocks: [TKey, string[]][] = [
    ["ems.unregistered", gov.data.unregistered],
    ["ems.deprecatedFiring", gov.data.deprecated_firing],
    ["ems.pendingReview", gov.data.pending_review],
    ["ems.noOwner", gov.data.no_owner],
    ["ems.noMetrics", gov.data.no_metrics],
    ["ems.staleDrafts", gov.data.stale_drafts],
  ];
  return (
    <div className={s.govGrid}>
      {blocks.map(([key, names]) => (
        <Card key={key} title={`${t(key)} · ${names.length}`}>
          {names.length === 0 ? (
            <span className="muted">—</span>
          ) : (
            <div className={s.chips}>
              {names.map((n) => (
                <Link key={n} to={`/ems?tab=registry&event=${n}`}>
                  <Badge mono>{n}</Badge>
                </Link>
              ))}
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}

export function GlobalParamsTab() {
  const { t } = useI18n();
  const can = useCan();
  const toast = useToast();
  const params = useGlobalParams();
  const m = useEmsMutations();
  const [draft, setDraft] = useState<ParamIn[] | null>(null);
  if (params.isPending) return <PageSpinner />;
  const value = draft ?? ((params.data ?? []) as ParamIn[]);
  const editable = can("events:approve");
  return (
    <Card
      title={t("ems.globalInherited")}
      actions={
        editable &&
        draft && (
          <Button
            variant="primary"
            loading={m.globals.isPending}
            onClick={() =>
              m.globals.mutate(draft, {
                onSuccess: () => {
                  setDraft(null);
                  toast.success(t("admin.saved"));
                },
                onError: (e) => toast.error(e.message),
              })
            }
          >
            {t("common.save")}
          </Button>
        )
      }
    >
      {editable ? (
        <ParamsEditor value={value} onChange={setDraft} />
      ) : (
        <ul>
          {value.map((p) => (
            <li key={p.name}>
              <code>{p.name}</code> — {p.type} {p.description}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const COLS = [
  "table",
  "name_column",
  "date_column",
  "time_column",
  "params_column",
  "user_column",
  "platform_column",
  "version_column",
] as const;

export function SettingsTab({ projectId }: { projectId: string }) {
  const { t } = useI18n();
  const can = useCan();
  const toast = useToast();
  const tracking = useTracking(projectId);
  const sources = useSources();
  const m = useEmsMutations();
  const [form, setForm] = useState<Record<string, string | number> | null>(null);
  if (tracking.isPending || sources.isPending) return <PageSpinner />;
  const value: Record<string, string | number> = form ?? {
    source_id: tracking.data?.source_id ?? sources.data?.[0]?.id ?? "",
    table: tracking.data?.table ?? "events",
    name_column: tracking.data?.name_column ?? "event_name",
    date_column: tracking.data?.date_column ?? "event_date",
    time_column: tracking.data?.time_column ?? "event_ts",
    params_column: tracking.data?.params_column ?? "params",
    user_column: tracking.data?.user_column ?? "user_id",
    platform_column: tracking.data?.platform_column ?? "platform",
    version_column: tracking.data?.version_column ?? "app_version",
    drop_threshold: tracking.data?.drop_threshold ?? 0.5,
  };
  const editable = can("events:approve", projectId);
  return (
    <Card
      title={t("ems.trackingSource")}
      actions={
        editable && (
          <Button
            variant="primary"
            loading={m.tracking.isPending}
            onClick={() =>
              m.tracking.mutate(
                { projectId, body: value as never },
                {
                  onSuccess: () => {
                    setForm(null);
                    toast.success(t("admin.saved"));
                  },
                  onError: (e) => toast.error(e.message),
                },
              )
            }
          >
            {t("common.save")}
          </Button>
        )
      }
    >
      {!tracking.data && <ErrorBox>{t("ems.notConfigured")}</ErrorBox>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14, marginTop: 12 }}>
        <Field label={t("data.pickSource")}>
          <Select
            value={String(value.source_id)}
            disabled={!editable}
            onChange={(e) => setForm({ ...value, source_id: e.target.value })}
          >
            {sources.data?.map((src) => (
              <option key={src.id} value={src.id}>
                {src.name}
              </option>
            ))}
          </Select>
        </Field>
        {COLS.map((c) => (
          <Field key={c} label={c}>
            <Input
              mono
              value={String(value[c])}
              disabled={!editable}
              onChange={(e) => setForm({ ...value, [c]: e.target.value })}
            />
          </Field>
        ))}
        <Field label={t("ems.dropThreshold")}>
          <Input
            type="number"
            step={0.05}
            min={0.05}
            max={0.95}
            value={value.drop_threshold}
            disabled={!editable}
            onChange={(e) => setForm({ ...value, drop_threshold: Number(e.target.value) })}
          />
        </Field>
      </div>
    </Card>
  );
}
