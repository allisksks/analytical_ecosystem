import { BarChart3, BookOpen, Database, FlaskConical, Home, Sparkles, Zap } from "lucide-react";
import type { ReactNode } from "react";
import type { TKey } from "../shared/i18n";

export interface NavItem {
  to: string;
  label: TKey;
  icon: ReactNode;
  end?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "nav.home", icon: <Home size={16} />, end: true },
  { to: "/data", label: "nav.data", icon: <Database size={16} /> },
  { to: "/ems", label: "nav.ems", icon: <Zap size={16} /> },
  { to: "/bi", label: "nav.bi", icon: <BarChart3 size={16} /> },
  { to: "/ab", label: "nav.ab", icon: <FlaskConical size={16} /> },
  { to: "/kb", label: "nav.kb", icon: <BookOpen size={16} /> },
  { to: "/assistant", label: "nav.ai", icon: <Sparkles size={16} /> },
];
