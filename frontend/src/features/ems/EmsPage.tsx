import clsx from "clsx";
import { Download, FileUp, Plus, ScanSearch, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { API_BASE } from "../../shared/api/client";
import { PageBody } from "../../layout/AppShell";
import { useI18n, type TKey } from "../../shared/i18n";
import { formatDateTime, formatNumber } from "../../shared/lib/format";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  MenuItem,
  PageHeader,
  PageSpinner,
  Popover,
  Table,
  Tabs,
  useToast,
} from "../../shared/ui";
import { useCan } from "../auth/AuthProvider";
import { useProject } from "../projects/ProjectProvider";
import { AlertsTab, GlobalParamsTab, GovernanceTab, SettingsTab } from "./EmsTabs";
import { DiscoverDialog, ImportDialog, NewEventDialog } from "./EmsDialogs";
import { EventDetail } from "./EventDetail";
import { useAlerts, useEmsMutations, useEvents, useRuns } from "./api";
import { HEALTH_TONE, STATUS_TONE } from "./emsStyle";
import s from "./ems.module.css";

type Section = "registry" | "alerts" | "governance" | "globalParams" | "settings";
const FORMATS = [
  ["json_schema", "JSON Schema"],
  ["typescript", "TypeScript"],
  ["kotlin", "Kotlin"],
  ["swift", "Swift"],
  ["csharp", "Unity C#"],
] as const;

async function download(path: string, filename: string) {
  const { authFetch } = await import("../../shared/api/client");
  const res = await authFetch(new Request(`${API_BASE}${path}`));
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function EmsPage() {
  const { t, locale } = useI18n();
  const can = useCan();
  const toast = useToast();
  const { project } = useProject();
  const pid = project?.id;
  const [params, setParams] = useSearchParams();
  const section = (params.get("tab") as Section | null) ?? "registry";
  const events = useEvents(pid);
  const alerts = useAlerts(pid);
  const runs = useRuns(pid);
  const m = useEmsMutations();
  const [q, setQ] = useState("");
  const [dialog, setDialog] = useState<"new" | "import" | "discover" | null>(null);
  const list = useMemo(
    () => (events.data ?? []).filter((e) => !q || e.name.includes(q.toLowerCase())),
    [events.data, q],
  );
  const selected = params.get("event")
    ? list.find((e) => e.name === params.get("event") || e.id === params.get("event"))
    : list[0];
  const lastRun = runs.data?.[0];
  if (!project)
    return (
      <PageBody>
        <EmptyState title={t("projects.none")} />
      </PageBody>
    );

  return (
    <PageBody wide>
      <PageHeader
        crumbs={[t("ems.title"), project.name]}
        title={t(`ems.${section}` as TKey)}
        subtitle={
          lastRun
            ? t("ems.lastRun", {
                date: formatDateTime(lastRun.started_at, locale),
                until: lastRun.data_until?.slice(0, 10) ?? "—",
              })
            : undefined
        }
        actions={
          <>
            {can("events:download", pid) && (
              <Popover
                align="end"
                trigger={({ toggle }) => (
                  <Button icon={<Download size={16} />} onClick={toggle}>
                    {t("ems.export")}
                  </Button>
                )}
              >
                {(close) => (
                  <>
                    {FORMATS.map(([f, label]) => (
                      <MenuItem
                        key={f}
                        onClick={() => {
                          close();
                          void download(`/ems/export?project_id=${pid}&format=${f}`, `${project.key}.${f}`).catch(
                            (e: Error) => toast.error(e.message),
                          );
                        }}
                      >
                        {label}
                      </MenuItem>
                    ))}
                    <MenuItem
                      onClick={() => {
                        close();
                        void download(`/ems/export/bundle?project_id=${pid}`, `${project.key}_events.zip`);
                      }}
                    >
                      ZIP
                    </MenuItem>
                  </>
                )}
              </Popover>
            )}
            {can("events:edit", pid) && (
              <>
                <Button icon={<FileUp size={16} />} onClick={() => setDialog("import")}>
                  {t("ems.import")}
                </Button>
                <Button icon={<ScanSearch size={16} />} onClick={() => setDialog("discover")}>
                  {t("ems.discover")}
                </Button>
                <Button
                  icon={<ShieldCheck size={16} />}
                  loading={m.validate.isPending}
                  onClick={() =>
                    m.validate.mutate(pid!, {
                      onSuccess: (r) => toast.info(`${t("ems.validate")}: ${r.status}`),
                      onError: (e) => toast.error(e.message),
                    })
                  }
                >
                  {t("ems.validate")}
                </Button>
                <Button variant="primary" icon={<Plus size={16} />} onClick={() => setDialog("new")}>
                  {t("ems.newEvent")}
                </Button>
              </>
            )}
          </>
        }
      />
      <Tabs<Section>
        variant="pills"
        value={section}
        onChange={(k) => setParams({ tab: k })}
        items={[
          { key: "registry", label: t("ems.registry"), count: events.data?.length },
          { key: "alerts", label: t("ems.alerts"), count: alerts.data?.length },
          { key: "governance", label: t("ems.governance") },
          { key: "globalParams", label: t("ems.globalParams") },
          { key: "settings", label: t("ems.settings") },
        ]}
      />
      <div style={{ marginTop: 16 }}>
        {section === "registry" &&
          (events.isPending ? (
            <PageSpinner />
          ) : (
            <div className={s.layout}>
              <Card padded={false}>
                <div className={s.toolbar}>
                  <Input placeholder={t("ems.search")} value={q} onChange={(e) => setQ(e.target.value)} />
                </div>
                <div className={s.list}>
                  <Table compact>
                    <thead>
                      <tr>
                        <th>{t("ems.name")}</th>
                        <th>{t("ems.version")}</th>
                        <th style={{ textAlign: "right" }}>{t("ems.lastDay")}</th>
                        <th>{t("ems.status")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {list.map((e) => (
                        <tr
                          key={e.id}
                          className={clsx(
                            s.row,
                            e.id === selected?.id && s.rowSelected,
                            e.health === "warning" && s.rowWarning,
                            e.health === "critical" && s.rowCritical,
                          )}
                          onClick={() => setParams({ tab: "registry", event: e.name })}
                        >
                          <td>
                            <span className={s.eventName}>{e.name}</span>
                            {e.pending_version && <Badge tone="warn">v{e.pending_version}?</Badge>}
                          </td>
                          <td>
                            {e.current_version ? (
                              <Badge mono tone="info">
                                v{e.current_version}
                              </Badge>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td style={{ textAlign: "right" }}>{formatNumber(e.last_count, locale)}</td>
                          <td>
                            {e.status === "active" ? (
                              <Badge tone={HEALTH_TONE[e.health]} dot>
                                {t(`ems.healths.${e.health}` as TKey)}
                              </Badge>
                            ) : (
                              <Badge tone={STATUS_TONE[e.status]}>{t(`ems.statuses.${e.status}` as TKey)}</Badge>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </div>
              </Card>
              {selected ? (
                <EventDetail id={selected.id} projectId={project.id} />
              ) : (
                <Card>
                  <EmptyState title={t("ems.newEvent")} />
                </Card>
              )}
            </div>
          ))}
        {section === "alerts" && <AlertsTab projectId={project.id} />}
        {section === "governance" && <GovernanceTab projectId={project.id} />}
        {section === "globalParams" && <GlobalParamsTab />}
        {section === "settings" && <SettingsTab projectId={project.id} />}
      </div>
      {dialog === "new" && <NewEventDialog projectId={project.id} onClose={() => setDialog(null)} />}
      {dialog === "import" && <ImportDialog projectId={project.id} onClose={() => setDialog(null)} />}
      {dialog === "discover" && <DiscoverDialog projectId={project.id} onClose={() => setDialog(null)} />}
    </PageBody>
  );
}
