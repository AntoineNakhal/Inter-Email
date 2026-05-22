import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "./AppShell";
import { DashboardPage } from "../routes/DashboardPage";
import { HomePage } from "../routes/HomePage";
import { InboxPage } from "../routes/InboxPage";
import { LoginPage } from "../routes/LoginPage";
import { RegisterPage } from "../routes/RegisterPage";
import { SettingsPage } from "../routes/SettingsPage";
import { TechnicalInfoPage } from "../routes/TechnicalInfoPage";
import { ThreadDetailPage } from "../routes/ThreadDetailPage";

export const router = createBrowserRouter([
  // Public routes — no AppShell, no auth check
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },

  // Protected routes — wrapped in AppShell (which handles the auth gate)
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/home" replace /> },
      { path: "home", element: <HomePage /> },
      { path: "inbox", element: <InboxPage /> },
      { path: "technical-info", element: <TechnicalInfoPage /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "threads/:threadId", element: <ThreadDetailPage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);
