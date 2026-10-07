import type { ReactNode } from "react";
import { Outlet } from "react-router";
import { ShellProvider } from "./shell";
import { Sidebar, type SideGroup } from "./Sidebar";
import { Topbar } from "./Topbar";
import s from "./AppShell.module.css";

export function AppShell({
  topbarExtra,
  nav,
  overlays,
}: {
  topbarExtra?: ReactNode;
  nav?: SideGroup[];
  overlays?: ReactNode;
}) {
  return (
    <ShellProvider>
      <div className={s.shell}>
        <a href="#main" className={s.skip}>
          Skip to content
        </a>
        <Topbar extra={topbarExtra} />
        <div className={s.body}>
          {nav && <Sidebar groups={nav} />}
          <main id="main" className={s.main}>
            <Outlet />
          </main>
        </div>
        {overlays}
      </div>
    </ShellProvider>
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
