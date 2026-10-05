import { BarChart3, Check, LayoutTemplate, Pencil, Plus, Share2, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import type { Dashboard, WidgetOut } from "../../shared/api/types";
import { PageBody } from "../../layout/AppShell";
import { useI18n } from "../../shared/i18n";
import { Button, Card, EmptyState, MenuItem, PageHeader, PageSpinner, Popover, Tabs } from "../../shared/ui";
import { useCan } from "../auth/AuthProvider";
import { useProject } from "../projects/ProjectProvider";
import { BlockEditor } from "./BlockEditor";
import { CohortsPage } from "./CohortsPage";
import { DashboardGrid } from "./DashboardGrid";
import { FilterBar, type FilterState } from "./FilterBar";
import { ShareDialog } from "./ShareDialog";
import { useBiMutations, useDashboard, useDashboards, useTemplates } from "./api";
import { defaultFilters, toGlobal } from "./filters";
import s from "./bi.module.css";

type Section = "dashboards" | "portfolio" | "cohorts";

export function BiPage() {
  const { t } = useI18n();
  const can = useCan();
  const navigate = useNavigate();
  const { section = "dashboards" } = useParams<{ section?: Section }>();
  const sections: { key: Section; label: string }[] = [
    { key: "dashboards", label: t("bi.dashboards") },
    ...(can("portfolio:view") ? [{ key: "portfolio" as Section, label: t("bi.portfolio") }] : []),
    { key: "cohorts", label: t("bi.cohorts") },
  ];
  return (
    <PageBody wide>
      <Tabs<Section>
        items={sections}
        value={section as Section}
        onChange={(k) => navigate(`/bi/${k}`)}
        variant="pills"
        className={s.header}
      />
      {section === "cohorts" ? <CohortsPage /> : <Dashboards portfolio={section === "portfolio"} />}
    </PageBody>
  );
}

function Dashboards({ portfolio }: { portfolio: boolean }) {
  const { t } = useI18n();
  const can = useCan();
  const { project } = useProject();
  const projectId = portfolio ? null : (project?.id ?? null);
  const list = useDashboards(projectId, portfolio);
  const templates = useTemplates();
  const m = useBiMutations();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("d") ?? list.data?.[0]?.id;
  const dash = useDashboard(selectedId);
  const canCreate = portfolio
    ? can("dashboards:edit") && can("portfolio:view")
    : can("dashboards:edit", projectId) || can("dashboards:edit_own", projectId);
  const scopeTemplates = (templates.data ?? []).filter((tp) => (tp.scope === "portfolio") === portfolio);
  const select = (id: string) => setParams({ d: id });

  if (list.isPending) return <PageSpinner />;

  const createMenu = canCreate && (
    <Popover
      align="end"
      trigger={({ toggle }) => (
        <Button variant="primary" icon={<Plus size={16} />} onClick={toggle}>
          {t("bi.newDashboard")}
        </Button>
      )}
    >
      {(close) => (
        <>
          <MenuItem
            icon={<BarChart3 size={16} />}
            onClick={() => {
              close();
              m.create.mutate(
                { project_id: projectId, title: t("bi.newDashboard"), description: "", filters: { period_days: 30 } },
                {
                  onSuccess: (d) => {
                    select(d.id);
                  },
                },
              );
            }}
          >
            {t("bi.newDashboard")}
          </MenuItem>
          {scopeTemplates.map((tp) => (
            <MenuItem
              key={tp.key}
              icon={<LayoutTemplate size={16} />}
              onClick={() => {
                close();
                m.fromTemplate.mutate(
                  { project_id: projectId, template_key: tp.key },
                  { onSuccess: (d) => select(d.id) },
                );
              }}
            >
              {t("bi.fromTemplate")}: {tp.title}
            </MenuItem>
          ))}
        </>
      )}
    </Popover>
  );

  if (!list.data?.length) {
    return (
      <Card>
        <EmptyState
          icon={<BarChart3 size={26} />}
          title={t("bi.noDashboards")}
          description={t("bi.noDashboardsHint")}
          action={createMenu}
        />
      </Card>
    );
  }

  return (
    <>
      <Tabs
        className={s.header}
        value={selectedId ?? ""}
        onChange={select}
        items={list.data.map((d) => ({ key: d.id, label: d.title }))}
      />
      {dash.isPending ? (
        <PageSpinner />
      ) : dash.data ? (
        <DashboardView
          key={dash.data.id}
          dashboard={dash.data}
          projectId={projectId}
          crumbs={["BI", portfolio ? t("bi.portfolio") : (project?.name ?? "")]}
          portfolio={portfolio}
          createMenu={createMenu}
          onDeleted={() => setParams({})}
        />
      ) : null}
    </>
  );
}

function DashboardView({
  dashboard,
  projectId,
  crumbs,
  portfolio,
  createMenu,
  onDeleted,
}: {
  dashboard: Dashboard;
  projectId: string | null;
  crumbs: string[];
  portfolio: boolean;
  createMenu: ReactNode;
  onDeleted: () => void;
}) {
  const { t } = useI18n();
  const m = useBiMutations();
  const [editing, setEditing] = useState(false);
  const [block, setBlock] = useState<WidgetOut | "new" | null>(null);
  const [sharing, setSharing] = useState(false);
  const [filters, setFilters] = useState<FilterState>(() =>
    defaultFilters(Number(dashboard.filters?.period_days ?? 30)),
  );
  const global = useMemo(() => toGlobal(filters), [filters]);
  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={dashboard.title}
        actions={
          <>
            {dashboard.can_edit && (
              <>
                <Button icon={<Share2 size={16} />} onClick={() => setSharing(true)}>
                  {t("bi.share")}
                </Button>
                {editing && (
                  <>
                    <Button
                      icon={<Trash2 size={16} />}
                      variant="ghost"
                      onClick={() => {
                        if (window.confirm(t("bi.deleteDashboardConfirm")))
                          m.remove.mutate(dashboard.id, { onSuccess: onDeleted });
                      }}
                    >
                      {t("common.delete")}
                    </Button>
                    <Button icon={<Plus size={16} />} onClick={() => setBlock("new")}>
                      {t("bi.addBlock")}
                    </Button>
                  </>
                )}
                <Button
                  variant={editing ? "primary" : "secondary"}
                  icon={editing ? <Check size={16} /> : <Pencil size={16} />}
                  onClick={() => setEditing((v) => !v)}
                >
                  {editing ? t("bi.done") : t("bi.edit")}
                </Button>
              </>
            )}
            {createMenu}
          </>
        }
      />
      <FilterBar
        value={filters}
        onChange={setFilters}
        projectId={projectId}
        dimensionKeys={portfolio ? ["app_id"] : ["platform", "country", "source"]}
      />
      <DashboardGrid dashboard={dashboard} filters={global} editing={editing} onConfigure={(w) => setBlock(w)} />
      {block && (
        <BlockEditor
          dashId={dashboard.id}
          projectId={projectId}
          widget={block === "new" ? null : block}
          filters={global}
          onClose={() => setBlock(null)}
        />
      )}
      {sharing && <ShareDialog dashboard={dashboard} onClose={() => setSharing(false)} />}
    </>
  );
}
