import clsx from "clsx";
import { BarChart3, Languages, Moon, Sun } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router";
import { useI18n } from "../shared/i18n";
import { useTheme } from "../shared/lib/theme";
import { IconButton } from "../shared/ui";
import { NAV_ITEMS, type NavItem } from "./nav";
import s from "./Topbar.module.css";

export function Topbar({ extra, items = NAV_ITEMS }: { extra?: ReactNode; items?: NavItem[] }) {
  const { t, locale, setLocale } = useI18n();
  const { resolved, setPref } = useTheme();
  return (
    <header className={s.topbar}>
      <NavLink to="/" className={s.brand} aria-label={t("app.name")}>
        <span className={s.mark} aria-hidden>
          <BarChart3 size={18} />
        </span>
        <span className={s.brandName}>Analytics</span>
      </NavLink>
      <nav className={s.tabs} aria-label="Modules">
        {items.map((it) => (
          <NavLink key={it.to} to={it.to} end={it.end} className={({ isActive }) => clsx(s.tab, isActive && s.active)}>
            {it.icon}
            <span>{t(it.label)}</span>
          </NavLink>
        ))}
      </nav>
      <div className={s.spacer} />
      <div className={s.right}>
        {extra}
        <IconButton
          label={`${t("common.language")}: ${locale.toUpperCase()}`}
          className={s.iconBtn}
          onClick={() => setLocale(locale === "ru" ? "en" : "ru")}
        >
          <Languages size={16} />
        </IconButton>
        <IconButton
          label={`${t("common.theme")}: ${resolved === "dark" ? t("common.dark") : t("common.light")}`}
          className={s.iconBtn}
          onClick={() => setPref(resolved === "dark" ? "light" : "dark")}
        >
          {resolved === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </IconButton>
      </div>
    </header>
  );
}
