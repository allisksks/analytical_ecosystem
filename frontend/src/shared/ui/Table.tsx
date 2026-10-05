import clsx from "clsx";
import type { ReactNode } from "react";
import s from "./Table.module.css";

export function Table({
  children,
  clickable,
  compact,
  className,
  maxHeight,
}: {
  children: ReactNode;
  clickable?: boolean;
  compact?: boolean;
  className?: string;
  maxHeight?: number | string;
}) {
  return (
    <div className={clsx(s.wrap, className)} style={maxHeight ? { maxHeight } : undefined}>
      <table className={clsx(s.table, clickable && s.clickable, compact && s.compact)}>{children}</table>
    </div>
  );
}
