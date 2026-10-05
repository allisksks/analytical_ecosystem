import { createBrowserRouter } from "react-router";
import { AbPage } from "../features/ab/AbPage";
import { DesignerPage } from "../features/ab/DesignerPage";
import { ExperimentPage } from "../features/ab/ExperimentPage";
import { AdminPage } from "../features/admin/AdminPage";
import { AssistantPage } from "../features/ai/AssistantPage";
import { BiPage } from "../features/bi/BiPage";
import { PublicDashboardPage } from "../features/bi/PublicDashboardPage";
import { EmsPage } from "../features/ems/EmsPage";
import { KbEditorPage } from "../features/kb/KbEditorPage";
import { KbItemPage } from "../features/kb/KbItemPage";
import { KbPage } from "../features/kb/KbPage";
import { DataPage } from "../features/data/DataPage";
import { LoginPage } from "../features/auth/LoginPage";
import { UserMenu } from "../features/auth/UserMenu";
import { ProjectPicker } from "../features/projects/ProjectPicker";
import { AppShell } from "../layout/AppShell";
import { HomePage } from "../pages/HomePage";
import { NotFoundPage } from "../pages/StatusPages";
import { Protected } from "./Protected";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/share/:token", element: <PublicDashboardPage /> },
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
          { path: "ems", element: <EmsPage /> },
          { path: "bi", element: <BiPage /> },
          { path: "bi/:section", element: <BiPage /> },
          { path: "ab", element: <AbPage /> },
          { path: "ab/new", element: <DesignerPage /> },
          { path: "ab/:id", element: <ExperimentPage /> },
          { path: "ab/:id/edit", element: <DesignerPage /> },
          { path: "assistant", element: <AssistantPage /> },
          { path: "kb", element: <KbPage /> },
          { path: "kb/new", element: <KbEditorPage /> },
          { path: "kb/:id", element: <KbItemPage /> },
          { path: "kb/:id/edit", element: <KbEditorPage /> },
          { path: "admin/*", element: <AdminPage /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);
