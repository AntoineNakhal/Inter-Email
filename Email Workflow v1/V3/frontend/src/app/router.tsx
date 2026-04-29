import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "./AppShell";
import { DashboardPage } from "../routes/DashboardPage";
import { InboxPage } from "../routes/InboxPage";
import { ReviewPage } from "../routes/ReviewPage";
import { SettingsPage } from "../routes/SettingsPage";
import { ThreadDetailPage } from "../routes/ThreadDetailPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "inbox", element: <InboxPage /> },
      { path: "review", element: <ReviewPage /> },
      { path: "threads/:threadId", element: <ThreadDetailPage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);
