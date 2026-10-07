import clsx from "clsx";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import s from "./Popover.module.css";

/** Click-to-open popover anchored to its trigger; closes on outside click and Escape. */
export function Popover({
  trigger,
  children,
  align = "start",
  className,
}: {
  trigger: (props: { open: boolean; toggle: () => void }) => ReactNode;
  children: (close: () => void) => ReactNode;
  align?: "start" | "end";
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div className={s.anchor} ref={ref}>
      {trigger({ open, toggle: () => setOpen((v) => !v) })}
      {open && <div className={clsx(s.panel, s[align], className)}>{children(() => setOpen(false))}</div>}
    </div>
  );
}

export function MenuItem({
  children,
  onClick,
  active,
  icon,
}: {
  children: ReactNode;
  onClick: () => void;
  active?: boolean;
  icon?: ReactNode;
}) {
  return (
    <button type="button" className={clsx(s.item, active && s.itemActive)} onClick={onClick}>
      {icon}
      <span>{children}</span>
    </button>
  );
}

export function MenuGroup({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className={s.group}>
      <div className={s.groupLabel}>{label}</div>
      {children}
    </div>
  );
}
