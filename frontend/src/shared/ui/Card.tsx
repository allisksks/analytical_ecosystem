import clsx from "clsx";
import type { HTMLAttributes, ReactNode } from "react";
import s from "./Card.module.css";

interface CardProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  padded?: boolean;
  accent?: string;
}

export function Card({
  title,
  subtitle,
  actions,
  padded = true,
  accent,
  className,
  children,
  style,
  ...rest
}: CardProps) {
  return (
    <section
      className={clsx(s.card, accent && s.accented, className)}
      style={accent ? { ...style, ["--card-accent" as string]: accent } : style}
      {...rest}
    >
      {(title || actions) && (
        <header className={s.head}>
          <div className={s.titles}>
            {title && <h3 className={s.title}>{title}</h3>}
            {subtitle && <p className={s.subtitle}>{subtitle}</p>}
          </div>
          {actions && <div className={s.actions}>{actions}</div>}
        </header>
      )}
      <div className={clsx(padded && s.body)}>{children}</div>
    </section>
  );
}
