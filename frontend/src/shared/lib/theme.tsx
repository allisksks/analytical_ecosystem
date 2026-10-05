import type { ReactNode } from "react";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { storage } from "./storage";

export type ThemePref = "light" | "dark" | "system";
interface ThemeValue {
  pref: ThemePref;
  resolved: "light" | "dark";
  setPref: (p: ThemePref) => void;
}

const ThemeContext = createContext<ThemeValue | null>(null);

function systemTheme(): "light" | "dark" {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(() => (storage.get("theme") as ThemePref | null) ?? "system");
  const [sys, setSys] = useState<"light" | "dark">(systemTheme);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const on = () => setSys(systemTheme());
    mq?.addEventListener("change", on);
    return () => mq?.removeEventListener("change", on);
  }, []);
  const resolved = pref === "system" ? sys : pref;
  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);
  const value = useMemo(
    () => ({
      pref,
      resolved,
      setPref: (p: ThemePref) => {
        storage.set("theme", p);
        setPrefState(p);
      },
    }),
    [pref, resolved],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme(): ThemeValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}
