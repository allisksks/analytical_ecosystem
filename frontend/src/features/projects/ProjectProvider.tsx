import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { Project } from "../../shared/api/types";
import { storage } from "../../shared/lib/storage";
import { useAuth } from "../auth/AuthProvider";

interface ProjectValue {
  projects: Project[];
  project: Project | null;
  setProjectId: (id: string) => void;
}

const ProjectContext = createContext<ProjectValue | null>(null);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  const projects = useMemo(() => me?.projects ?? [], [me]);
  const [selected, setSelected] = useState<string | null>(() => storage.get("project"));
  const project = projects.find((p) => p.id === selected) ?? projects[0] ?? null;
  const setProjectId = useCallback((id: string) => {
    storage.set("project", id);
    setSelected(id);
  }, []);
  const value = useMemo(() => ({ projects, project, setProjectId }), [projects, project, setProjectId]);
  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useProject(): ProjectValue {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error("useProject must be used inside <ProjectProvider>");
  return ctx;
}
