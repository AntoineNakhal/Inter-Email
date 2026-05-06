import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "./AppShell";
import { DashboardPage } from "../routes/DashboardPage";
import { HomePage } from "../routes/HomePage";
import { InboxPage } from "../routes/InboxPage";
import { SettingsPage } from "../routes/SettingsPage";
import { ThreadDetailPage } from "../routes/ThreadDetailPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/home" replace /> },
      { path: "home", element: <HomePage /> },
      { path: "inbox", element: <InboxPage /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "threads/:threadId", element: <ThreadDetailPage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);
