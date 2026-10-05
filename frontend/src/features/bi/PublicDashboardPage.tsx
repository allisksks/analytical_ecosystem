import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useParams } from "react-router";
import { PageBody } from "../../layout/AppShell";
import { api } from "../../shared/api/client";
import { useI18n } from "../../shared/i18n";
import { Badge, Card, EmptyState, PageHeader, PageSpinner } from "../../shared/ui";
import { DashboardGrid } from "./DashboardGrid";
import { FilterBar, type FilterState } from "./FilterBar";
import { defaultFilters, toGlobal } from "./filters";

/** Read-only dashboard opened by a time-limited public link (no sign-in). */
export function PublicDashboardPage() {
  const { t } = useI18n();
  const { token = "" } = useParams();
  const dash = useQuery({
    queryKey: ["public-dashboard", token],
    queryFn: async () => (await api.GET("/api/v1/public/dashboards/{token}", { params: { path: { token } } })).data!,
    retry: false,
  });
  const [filters, setFilters] = useState<FilterState>(() => defaultFilters());
  const global = useMemo(() => toGlobal({ ...filters, filters: [] }), [filters]);
  if (dash.isPending) return <PageSpinner />;
  if (!dash.data)
    return (
      <PageBody>
        <Card>
          <EmptyState title={dash.error?.message ?? t("common.notFound")} />
        </Card>
      </PageBody>
    );
  return (
    <PageBody wide>
      <PageHeader
        crumbs={[t("bi.publicTitle")]}
        title={dash.data.title}
        actions={<Badge tone="info">read-only</Badge>}
      />
      <FilterBar value={filters} onChange={setFilters} projectId={null} dimensionKeys={[]} />
      <DashboardGrid
        dashboard={{ ...dash.data, can_edit: false }}
        filters={global}
        editing={false}
        publicToken={token}
      />
    </PageBody>
  );
}
