import type {
  DraftDocument,
  EmailThread,
  GmailConnectionStatus,
  QueueDashboardResponse,
  RuntimeSettingsUpdate,
  SettingsSummary,
  SyncRunStatus,
  ThreadListResponse,
} from "../types/api";

const API_ROOT =
  `${import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"}/api/v1`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const apiClient = {
  health: () => request<{ status: string }>("/health"),
  listThreads: () => request<ThreadListResponse>("/threads"),
  getThread: (threadId: string) => request<EmailThread>(`/threads/${threadId}`),
  getQueueSummary: () => request<QueueDashboardResponse>("/queue/summary"),
  startSync: (source = "anywhere", maxResults = 50) =>
    request<SyncRunStatus>("/sync", {
      method: "POST",
      body: JSON.stringify({ source, max_results: maxResults }),
    }),
  getLatestSyncRunStatus: async () => {
    try {
      return await request<SyncRunStatus>("/sync/runs/latest");
    } catch (error) {
      if (error instanceof Error && error.message.includes("No sync runs found")) {
        return null;
      }
      throw error;
    }
  },
  getSyncRunStatus: (runId: number) =>
    request<SyncRunStatus>(`/sync/runs/${runId}`),
  saveReview: (threadId: string, payload: Record<string, unknown>) =>
    request<{ status: string }>(`/threads/${threadId}/review`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  markSeen: (threadId: string, seen: boolean) =>
    request<{ status: string }>(`/threads/${threadId}/seen`, {
      method: "POST",
      body: JSON.stringify({ seen }),
    }),
  getDraft: (threadId: string) =>
    request<DraftDocument | null>(`/threads/${threadId}/draft`),
  generateDraft: (threadId: string, payload: Record<string, unknown>) =>
    request<DraftDocument>(`/threads/${threadId}/draft`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getSettings: () => request<SettingsSummary>("/settings"),
  updateSettings: (payload: RuntimeSettingsUpdate) =>
    request<SettingsSummary>("/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  getGmailConnectionStatus: () =>
    request<GmailConnectionStatus>("/gmail/connection"),
};
