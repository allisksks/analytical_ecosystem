import type { ReactNode } from "react";
import { Outlet } from "react-router";
import { Topbar } from "./Topbar";
import s from "./AppShell.module.css";

export function AppShell({ topbarExtra }: { topbarExtra?: ReactNode }) {
  return (
    <div className={s.shell}>
      <a href="#main" className={s.skip}>
        Skip to content
      </a>
      <Topbar extra={topbarExtra} />
      <main id="main" className={s.main}>
        <Outlet />
      </main>
    </div>
  );
}

/** Two-column page body: a left sidebar (tree, filters) and the content. */
export function WithSidebar({ sidebar, children }: { sidebar: ReactNode; children: ReactNode }) {
  return (
    <div className={s.withSidebar}>
      <aside className={s.sidebar}>{sidebar}</aside>
      <div className={s.content}>{children}</div>
    </div>
  );
}

export function PageBody({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return <div className={wide ? s.pageWide : s.page}>{children}</div>;
}
