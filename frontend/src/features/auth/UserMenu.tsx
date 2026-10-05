import { Languages, LogOut, Moon, Settings, Sun } from "lucide-react";
import { useNavigate } from "react-router";
import { useI18n } from "../../shared/i18n";
import { useTheme } from "../../shared/lib/theme";
import { MenuGroup, MenuItem, Popover } from "../../shared/ui";
import { useAuth } from "./AuthProvider";
import s from "./UserMenu.module.css";

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

export function UserMenu() {
  const { t, locale, setLocale } = useI18n();
  const { resolved, setPref } = useTheme();
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  if (!me) return null;
  const roles = [...new Set(me.user.memberships.map((m) => m.role_name))];
  return (
    <Popover
      align="end"
      trigger={({ toggle, open }) => (
        <button className={s.trigger} onClick={toggle} aria-expanded={open} aria-label={me.user.name}>
          <span className={s.who}>
            <span className={s.name}>{me.user.name}</span>
            <span className={s.role}>{roles[0] ?? "—"}</span>
          </span>
          <span className={s.avatar} aria-hidden>
            {initials(me.user.name)}
          </span>
        </button>
      )}
    >
      {(close) => (
        <>
          <div className={s.head}>
            <strong>{me.user.name}</strong>
            <span>{me.user.email}</span>
            <span className={s.roles}>{roles.join(", ")}</span>
          </div>
          <MenuGroup label={me.org_name}>
            {me.is_admin && (
              <MenuItem
                icon={<Settings size={16} />}
                onClick={() => {
                  close();
                  navigate("/admin");
                }}
              >
                {t("nav.admin")}
              </MenuItem>
            )}
            <MenuItem icon={<Languages size={16} />} onClick={() => setLocale(locale === "ru" ? "en" : "ru")}>
              {t("common.language")}: {locale === "ru" ? "English" : "Русский"}
            </MenuItem>
            <MenuItem
              icon={resolved === "dark" ? <Sun size={16} /> : <Moon size={16} />}
              onClick={() => setPref(resolved === "dark" ? "light" : "dark")}
            >
              {t("common.theme")}: {resolved === "dark" ? t("common.light") : t("common.dark")}
            </MenuItem>
            <MenuItem icon={<LogOut size={16} />} onClick={() => void logout()}>
              {t("common.signOut")}
            </MenuItem>
          </MenuGroup>
        </>
      )}
    </Popover>
  );
}
