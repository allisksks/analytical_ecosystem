import { createBrowserRouter } from "react-router";
import { AppShell } from "../layout/AppShell";
import { ComingSoonPage, NotFoundPage } from "../pages/StatusPages";
import { HomePage } from "../pages/HomePage";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "data/*", element: <ComingSoonPage titleKey="nav.data" /> },
      { path: "ems/*", element: <ComingSoonPage titleKey="nav.ems" /> },
      { path: "bi/*", element: <ComingSoonPage titleKey="nav.bi" /> },
      { path: "ab/*", element: <ComingSoonPage titleKey="nav.ab" /> },
      { path: "kb/*", element: <ComingSoonPage titleKey="nav.kb" /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
