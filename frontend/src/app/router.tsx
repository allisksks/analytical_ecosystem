import { createBrowserRouter } from "react-router";
import { AdminPage } from "../features/admin/AdminPage";
import { DataPage } from "../features/data/DataPage";
import { LoginPage } from "../features/auth/LoginPage";
import { UserMenu } from "../features/auth/UserMenu";
import { ProjectPicker } from "../features/projects/ProjectPicker";
import { AppShell } from "../layout/AppShell";
import { HomePage } from "../pages/HomePage";
import { ComingSoonPage, NotFoundPage } from "../pages/StatusPages";
import { Protected } from "./Protected";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <Protected />,
    children: [
      {
        element: (
          <AppShell
            topbarExtra={
              <>
                <ProjectPicker />
                <UserMenu />
              </>
            }
          />
        ),
        children: [
          { index: true, element: <HomePage /> },
          { path: "data/*", element: <DataPage /> },
          { path: "ems/*", element: <ComingSoonPage titleKey="nav.ems" /> },
          { path: "bi/*", element: <ComingSoonPage titleKey="nav.bi" /> },
          { path: "ab/*", element: <ComingSoonPage titleKey="nav.ab" /> },
          { path: "kb/*", element: <ComingSoonPage titleKey="nav.kb" /> },
          { path: "admin/*", element: <AdminPage /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);
