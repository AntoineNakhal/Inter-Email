import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "./AppShell";
import { InboxPage } from "../routes/InboxPage";
import { ReviewPage } from "../routes/ReviewPage";
import { SettingsPage } from "../routes/SettingsPage";
import { ThreadDetailPage } from "../routes/ThreadDetailPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/inbox" replace /> },
      { path: "inbox", element: <InboxPage /> },
      { path: "review", element: <ReviewPage /> },
      { path: "threads/:threadId", element: <ThreadDetailPage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);
