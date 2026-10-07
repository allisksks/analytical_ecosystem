import { Navigate, Route, Routes, useLocation } from "react-router";
import { PageBody } from "../../layout/AppShell";
import { useI18n } from "../../shared/i18n";
import { PageHeader } from "../../shared/ui";
import { CatalogPage } from "./CatalogPage";
import { MetricsPage } from "./MetricsPage";
import { SourcesPage } from "./SourcesPage";
import { SqlPage } from "./SqlPage";

type Section = "sources" | "catalog" | "metrics" | "sql";

export function DataPage() {
  const { t } = useI18n();
  const location = useLocation();
  const section = (location.pathname.split("/")[2] as Section | undefined) ?? "sources";
  return (
    <PageBody wide={section === "sql"}>
      <PageHeader crumbs={[t("nav.data")]} title={t(`data.${section}`)} />
      <Routes>
        <Route index element={<Navigate to="sources" replace />} />
        <Route path="sources" element={<SourcesPage />} />
        <Route path="catalog" element={<CatalogPage />} />
        <Route path="metrics" element={<MetricsPage />} />
        <Route path="sql" element={<SqlPage />} />
      </Routes>
    </PageBody>
  );
}
