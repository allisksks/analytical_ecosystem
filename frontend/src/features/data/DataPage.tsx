import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import { PageBody } from "../../layout/AppShell";
import { useI18n } from "../../shared/i18n";
import { PageHeader, Tabs } from "../../shared/ui";
import { CatalogPage } from "./CatalogPage";
import { SourcesPage } from "./SourcesPage";
import { SqlPage } from "./SqlPage";
import s from "./data.module.css";

type Section = "sources" | "catalog" | "sql";

export function DataPage() {
  const { t } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const section = (location.pathname.split("/")[2] as Section | undefined) ?? "sources";
  return (
    <PageBody wide={section === "sql"}>
      <PageHeader crumbs={[t("nav.data")]} title={t(`data.${section}`)} />
      <Tabs<Section>
        className={s.tabsBar}
        value={section}
        onChange={(k) => navigate(`/data/${k}${location.search}`)}
        items={[
          { key: "sources", label: t("data.sources") },
          { key: "catalog", label: t("data.catalog") },
          { key: "sql", label: t("data.sql") },
        ]}
      />
      <Routes>
        <Route index element={<Navigate to="sources" replace />} />
        <Route path="sources" element={<SourcesPage />} />
        <Route path="catalog" element={<CatalogPage />} />
        <Route path="sql" element={<SqlPage />} />
      </Routes>
    </PageBody>
  );
}
