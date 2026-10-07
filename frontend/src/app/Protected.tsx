import { Outlet } from "react-router";
import { RequireAuth } from "../features/auth/RequireAuth";
import { ProjectProvider } from "../features/projects/ProjectProvider";

export function Protected() {
  return (
    <RequireAuth>
      <ProjectProvider>
        <Outlet />
      </ProjectProvider>
    </RequireAuth>
  );
}
