import clsx from "clsx";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router";
import { useI18n, type TKey } from "../shared/i18n";
import { storage } from "../shared/lib/storage";
import { useState } from "react";
import { useShell } from "./shell";
import s from "./Sidebar.module.css";

export interface SideItem {
  to: string;
  label: TKey;
  icon: ReactNode;
  end?: boolean;
  badge?: number;
  badgeTone?: "neg" | "info";
}

export interface SideGroup {
  label?: TKey;
  items: SideItem[];
}

export function Sidebar({ groups, footer }: { groups: SideGroup[]; footer?: ReactNode }) {
  const { t } = useI18n();
  const { navOpen, setNavOpen } = useShell();
  const [collapsed, setCollapsed] = useState(() => storage.get("nav:collapsed") === "1");
  const location = useLocation();
  const toggle = () => {
    storage.set("nav:collapsed", collapsed ? "0" : "1");
    setCollapsed(!collapsed);
  };
  const isActive = (it: SideItem) => {
    const [path, query] = it.to.split("?");
    const pathOk = it.end
      ? location.pathname === path
      : location.pathname === path || location.pathname.startsWith(`${path}/`);
    return pathOk && (!query || location.search.includes(query));
  };
  return (
    <>
      {navOpen && <div className={s.backdrop} onClick={() => setNavOpen(false)} aria-hidden />}
      <aside className={clsx(s.sidebar, collapsed && s.collapsed, navOpen && s.open)} aria-label={t("nav.menu")}>
        <nav className={s.nav}>
          {groups.map((g, gi) => (
            <div key={gi} className={s.group}>
              {g.label && <div className={s.groupLabel}>{t(g.label)}</div>}
              {g.items.map((it) => (
                <NavLink
                  key={it.to}
                  to={it.to}
                  className={clsx(s.item, isActive(it) && s.active)}
                  aria-current={isActive(it) ? "page" : undefined}
                  title={collapsed ? t(it.label) : undefined}
                  onClick={() => setNavOpen(false)}
                >
                  <span className={s.icon}>{it.icon}</span>
                  <span className={s.label}>{t(it.label)}</span>
                  {!!it.badge && (
                    <span className={clsx(s.badge, it.badgeTone === "neg" && s.badgeNeg)} aria-label={String(it.badge)}>
                      {it.badge > 99 ? "99+" : it.badge}
                    </span>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        {footer && <div className={s.footer}>{footer}</div>}
        <button
          type="button"
          className={s.collapse}
          onClick={toggle}
          aria-label={collapsed ? t("nav.expand") : t("nav.collapse")}
        >
          {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          <span className={s.label}>{t("nav.collapse")}</span>
        </button>
      </aside>
    </>
  );
}
