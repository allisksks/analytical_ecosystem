import clsx from "clsx";
import type { ReactNode } from "react";
import s from "./misc.module.css";

export function PageHeader({
  crumbs = [],
  title,
  subtitle,
  actions,
}: {
  crumbs?: ReactNode[];
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className={s.pageHeader}>
      <div className={s.pageTitles}>
        <h1 className={s.pageTitle}>
          {crumbs.map((c, i) => (
            <span key={i} className={s.crumb}>
              {c}
              <span className={s.sep}>/</span>
            </span>
          ))}
          <span className={s.current}>{title}</span>
        </h1>
        {subtitle && <p className={s.pageSubtitle}>{subtitle}</p>}
      </div>
      {actions && <div className={s.pageActions}>{actions}</div>}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={s.empty}>
      {icon && <div className={s.emptyIcon}>{icon}</div>}
      <div className={s.emptyTitle}>{title}</div>
      {description && <div className={s.emptyDesc}>{description}</div>}
      {action && <div className={s.emptyAction}>{action}</div>}
    </div>
  );
}

export function KpiTile({
  label,
  value,
  delta,
  tone,
  hint,
}: {
  label: ReactNode;
  value: ReactNode;
  delta?: ReactNode;
  tone?: "pos" | "neg" | "neutral";
  hint?: ReactNode;
}) {
  return (
    <div className={s.kpi}>
      <div className={s.kpiLabel}>{label}</div>
      <div className={s.kpiValue}>{value}</div>
      {delta && <div className={clsx(s.kpiDelta, tone && s[tone])}>{delta}</div>}
      {hint && <div className={s.kpiHint}>{hint}</div>}
    </div>
  );
}

export function ErrorBox({ title, children }: { title?: ReactNode; children?: ReactNode }) {
  return (
    <div className={s.errorBox} role="alert">
      {title && <strong>{title}</strong>}
      {children && <div>{children}</div>}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className={s.kbd}>{children}</kbd>;
}

export function Skeleton({ height = 16, width = "100%" }: { height?: number; width?: number | string }) {
  return <span className={s.skeleton} style={{ height, width }} aria-hidden />;
}
