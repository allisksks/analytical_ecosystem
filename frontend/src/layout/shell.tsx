import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

/** Global overlays of the app shell: the command palette (Ctrl+K) and the assistant panel (Ctrl+J). */
interface ShellState {
  paletteOpen: boolean;
  setPaletteOpen: (v: boolean) => void;
  assistantOpen: boolean;
  /** Opens the assistant panel, optionally asking a question right away. */
  openAssistant: (question?: string) => void;
  closeAssistant: () => void;
  /** Last question sent from elsewhere (palette, home); ``n`` changes on every request. */
  request: { q: string; n: number } | null;
  navOpen: boolean;
  setNavOpen: (v: boolean) => void;
}

const ShellContext = createContext<ShellState | null>(null);

export function ShellProvider({ children }: { children: ReactNode }) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [request, setRequest] = useState<{ q: string; n: number } | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const openAssistant = useCallback((q?: string) => {
    if (q) setRequest((r) => ({ q, n: (r?.n ?? 0) + 1 }));
    setAssistantOpen(true);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      const key = e.key.toLowerCase();
      if (key === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      } else if (key === "j") {
        e.preventDefault();
        setAssistantOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const value = useMemo(
    () => ({
      paletteOpen,
      setPaletteOpen,
      assistantOpen,
      openAssistant,
      closeAssistant: () => setAssistantOpen(false),
      request,
      navOpen,
      setNavOpen,
    }),
    [paletteOpen, assistantOpen, openAssistant, request, navOpen],
  );
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useShell(): ShellState {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error("useShell outside ShellProvider");
  return ctx;
}
