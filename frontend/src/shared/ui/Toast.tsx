import clsx from "clsx";
import { CheckCircle2, Info, TriangleAlert, X } from "lucide-react";
import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import s from "./Toast.module.css";

type ToastKind = "success" | "error" | "info";
interface ToastItem {
  id: number;
  kind: ToastKind;
  message: ReactNode;
}
interface ToastApi {
  success: (m: ReactNode) => void;
  error: (m: ReactNode) => void;
  info: (m: ReactNode) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);
  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const push = useCallback(
    (kind: ToastKind, message: ReactNode) => {
      const id = ++seq.current;
      setItems((xs) => [...xs.slice(-3), { id, kind, message }]);
      window.setTimeout(() => dismiss(id), kind === "error" ? 7000 : 4000);
    },
    [dismiss],
  );
  const api = useMemo<ToastApi>(
    () => ({
      success: (m) => push("success", m),
      error: (m) => push("error", m),
      info: (m) => push("info", m),
    }),
    [push],
  );
  const icons = { success: <CheckCircle2 size={18} />, error: <TriangleAlert size={18} />, info: <Info size={18} /> };
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className={s.stack} aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={clsx(s.toast, s[t.kind])} role={t.kind === "error" ? "alert" : "status"}>
            {icons[t.kind]}
            <div className={s.msg}>{t.message}</div>
            <button className={s.close} onClick={() => dismiss(t.id)} aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
