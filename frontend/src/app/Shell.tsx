import {
  BookOpen,
  Briefcase,
  Database,
  FlaskConical,
  Inbox,
  LayoutDashboard,
  Settings,
  Sigma,
  Sparkles,
  Table2,
  TerminalSquare,
  Users,
  Zap,
} from "lucide-react";
import { AssistantButton, AssistantDrawer } from "../features/ai/AssistantDrawer";
import { useCan } from "../features/auth/AuthProvider";
import { UserMenu } from "../features/auth/UserMenu";
import { CommandPalette } from "../features/command/CommandPalette";
import { useInbox } from "../features/inbox/api";
import { ProjectPicker } from "../features/projects/ProjectPicker";
import { useProject } from "../features/projects/ProjectProvider";
import { AppShell } from "../layout/AppShell";
import type { SideGroup, SideItem } from "../layout/Sidebar";

const ADMIN = ["admin:users", "admin:roles", "admin:projects", "admin:audit", "admin:tokens"];

/** Navigation grouped by what people do, filtered by permissions, with badges from the inbox. */
// eslint-disable-next-line react-refresh/only-export-components
export function useNavGroups(): SideGroup[] {
  const can = useCan();
  const { project } = useProject();
  const inbox = useInbox(project?.id).data;
  const c = inbox?.counts;
  const any = (...perms: string[]) => perms.some((p) => can(p));
  const item = (ok: boolean, it: SideItem): SideItem[] => (ok ? [it] : []);
  const groups: SideGroup[] = [
    { items: [{ to: "/", end: true, label: "nav.inbox", icon: <Inbox size={18} />, badge: inbox?.tasks.length }] },
    {
      label: "nav.groups.analysis",
      items: [
        ...item(any("dashboards:view", "dashboards:view_shared"), {
          to: "/bi",
          end: true,
          label: "nav.dashboards",
          icon: <LayoutDashboard size={18} />,
        }),
        ...item(can("portfolio:view"), { to: "/bi/portfolio", label: "nav.portfolio", icon: <Briefcase size={18} /> }),
        ...item(can("semantic:view"), { to: "/bi/cohorts", label: "nav.cohorts", icon: <Users size={18} /> }),
        ...item(any("sql:run", "sql:run_all"), {
          to: "/data/sql",
          label: "nav.sql",
          icon: <TerminalSquare size={18} />,
        }),
        ...item(can("kb:ask"), { to: "/assistant", label: "nav.ai", icon: <Sparkles size={18} /> }),
      ],
    },
    {
      label: "nav.groups.product",
      items: [
        ...item(can("events:view"), {
          to: "/ems",
          label: "nav.ems",
          icon: <Zap size={18} />,
          badge: (c?.event_reviews ?? 0) + (c?.ai_drafts ?? 0) + (c?.alerts ?? 0) || undefined,
          badgeTone: c?.alerts ? "neg" : "info",
        }),
        ...item(any("experiments:view", "experiments:results"), {
          to: "/ab",
          label: "nav.ab",
          icon: <FlaskConical size={18} />,
          badge: (c?.experiment_reviews ?? 0) + (c?.experiment_decisions ?? 0) || undefined,
        }),
      ],
    },
    {
      label: "nav.groups.knowledge",
      items: [...item(can("kb:view"), { to: "/kb", label: "nav.kb", icon: <BookOpen size={18} /> })],
    },
    {
      label: "nav.groups.data",
      items: [
        ...item(can("semantic:view"), { to: "/data/metrics", label: "nav.metrics", icon: <Sigma size={18} /> }),
        ...item(can("catalog:view"), { to: "/data/catalog", label: "nav.catalog", icon: <Table2 size={18} /> }),
        ...item(can("connectors:view"), { to: "/data/sources", label: "nav.sources", icon: <Database size={18} /> }),
      ],
    },
    { items: [...item(any(...ADMIN), { to: "/admin", label: "nav.admin", icon: <Settings size={18} /> })] },
  ];
  return groups.filter((g) => g.items.length > 0);
}

export function Shell() {
  const nav = useNavGroups();
  return (
    <AppShell
      nav={nav}
      topbarExtra={
        <>
          <ProjectPicker />
          <AssistantButton />
          <UserMenu />
        </>
      }
      overlays={
        <>
          <CommandPalette nav={nav} />
          <AssistantDrawer />
        </>
      }
    />
  );
}
