import clsx from "clsx";
import type { ReactNode } from "react";
import s from "./Badge.module.css";

export type Tone = "pos" | "neg" | "info" | "warn" | "neutral" | "violet";

export function Badge({
  tone = "neutral",
  dot,
  mono,
  children,
  title,
}: {
  tone?: Tone;
  dot?: boolean;
  mono?: boolean;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={clsx(s.badge, s[tone], mono && s.mono)} title={title}>
      {dot && <span className={s.dot} aria-hidden />}
      {children}
    </span>
  );
}
