import clsx from "clsx";
import type { ReactNode } from "react";
import { useId } from "react";
import s from "./Tabs.module.css";

export interface TabItem<K extends string> {
  key: K;
  label: ReactNode;
  count?: number;
  icon?: ReactNode;
}

export function Tabs<K extends string>({
  items,
  value,
  onChange,
  variant = "underline",
  className,
}: {
  items: TabItem<K>[];
  value: K;
  onChange: (key: K) => void;
  variant?: "underline" | "pills";
  className?: string;
}) {
  const id = useId();
  const onKeyDown = (e: React.KeyboardEvent, idx: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = (idx + (e.key === "ArrowRight" ? 1 : -1) + items.length) % items.length;
    onChange(items[next].key);
    document.getElementById(`${id}-${items[next].key}`)?.focus();
  };
  return (
    <div role="tablist" className={clsx(s.tabs, s[variant], className)}>
      {items.map((it, idx) => {
        const active = it.key === value;
        return (
          <button
            key={it.key}
            id={`${id}-${it.key}`}
            role="tab"
            type="button"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            className={clsx(s.tab, active && s.active)}
            onClick={() => onChange(it.key)}
            onKeyDown={(e) => onKeyDown(e, idx)}
          >
            {it.icon}
            {it.label}
            {it.count !== undefined && <span className={s.count}>{it.count}</span>}
          </button>
        );
      })}
    </div>
  );
}
