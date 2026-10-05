import clsx from "clsx";
import { FolderTree, KeyRound, ScrollText, Shield, Users } from "lucide-react";
import { NavLink, Navigate, Route, Routes } from "react-router";
import { PageBody } from "../../layout/AppShell";
import { useI18n } from "../../shared/i18n";
import { PageHeader } from "../../shared/ui";
import { useAuth } from "../auth/AuthProvider";
import { AuditSection } from "./AuditSection";
import { ProjectsSection } from "./ProjectsSection";
import { RolesSection } from "./RolesSection";
import { TokensSection } from "./TokensSection";
import { UsersSection } from "./UsersSection";
import s from "./admin.module.css";

export function AdminPage() {
  const { t } = useI18n();
  const { me } = useAuth();
  if (!me?.is_admin) return <Navigate to="/" replace />;
  const links = [
    { to: "users", label: t("admin.users"), icon: <Users size={16} /> },
    { to: "roles", label: t("admin.roles"), icon: <Shield size={16} /> },
    { to: "projects", label: t("admin.projects"), icon: <FolderTree size={16} /> },
    { to: "tokens", label: t("admin.tokens"), icon: <KeyRound size={16} /> },
    { to: "audit", label: t("admin.audit"), icon: <ScrollText size={16} /> },
  ];
  return (
    <PageBody>
      <PageHeader title={t("admin.title")} />
      <div className={s.layout}>
        <nav className={s.nav}>
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} className={({ isActive }) => clsx(s.navLink, isActive && s.navActive)}>
              {l.icon}
              {l.label}
            </NavLink>
          ))}
        </nav>
        <div>
          <Routes>
            <Route index element={<Navigate to="users" replace />} />
            <Route path="users" element={<UsersSection />} />
            <Route path="roles" element={<RolesSection />} />
            <Route path="projects" element={<ProjectsSection />} />
            <Route path="tokens" element={<TokensSection />} />
            <Route path="audit" element={<AuditSection />} />
          </Routes>
        </div>
      </div>
    </PageBody>
  );
}
