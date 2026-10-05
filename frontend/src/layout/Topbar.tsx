import { BarChart3, Languages, Menu, Moon, Search, Sun } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router";
import { useI18n } from "../shared/i18n";
import { useTheme } from "../shared/lib/theme";
import { IconButton, Kbd } from "../shared/ui";
import { useShell } from "./shell";
import s from "./Topbar.module.css";

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

export function Topbar({ extra }: { extra?: ReactNode }) {
  const { t, locale, setLocale } = useI18n();
  const { resolved, setPref } = useTheme();
  const { setPaletteOpen, navOpen, setNavOpen } = useShell();
  return (
    <header className={s.topbar}>
      <IconButton label={t("nav.menu")} className={`${s.iconBtn} ${s.burger}`} onClick={() => setNavOpen(!navOpen)}>
        <Menu size={18} />
      </IconButton>
      <NavLink to="/" className={s.brand} aria-label={t("app.name")}>
        <span className={s.mark} aria-hidden>
          <BarChart3 size={18} />
        </span>
        <span className={s.brandName}>Analytics</span>
      </NavLink>
      <button type="button" className={s.search} onClick={() => setPaletteOpen(true)} aria-keyshortcuts="Control+K">
        <Search size={16} aria-hidden />
        <span className={s.searchText}>{t("shell.search")}</span>
        <span className={s.searchKbd}>
          <Kbd>{isMac ? "⌘" : "Ctrl"}</Kbd>
          <Kbd>K</Kbd>
        </span>
      </button>
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
