import type {
  DraftDocument,
  EmailThread,
  GmailConnectionStatus,
  KbChunkListResponse,
  KbChunkSummary,
  KbChunkUpdateRequest,
  KbDiagnoseResponse,
  KbDocument,
  KbDocumentListResponse,
  KbFinalizeRequest,
  KbUploadResponse,
  KbYouTubeIngestRequest,
  QueueDashboardResponse,
  RuntimeSettingsUpdate,
  SettingsSummary,
  SyncRunStatus,
  ThreadListResponse,
  ThreadOverride,
  ThreadOverrideRequest,
} from "../types/api";

const API_ROOT = `${import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"}/api/v1`;

let refreshPromise: Promise<boolean> | null = null;

function buildRequestInit(init?: RequestInit): RequestInit {
  return {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  };
}

async function doFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_ROOT}${path}`, buildRequestInit(init));
}

async function refreshAuthSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const response = await doFetch("/auth/refresh", { method: "POST" });
        return response.ok;
      } catch {
        return false;
      } finally {
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

async function parseError(response: Response): Promise<Error> {
  const raw = await response.text();
  let detail = raw;
  try {
    const parsed = JSON.parse(raw) as { detail?: string };
    if (parsed?.detail) {
      detail = parsed.detail;
    }
  } catch {
    // Non-JSON error body; keep the raw text.
  }
  return new Error(detail || `Request failed with ${response.status}`);
}

async function request<T>(path: string, init?: RequestInit, allowRefresh = true): Promise<T> {
  let response = await doFetch(path, init);

  if (response.status === 401 && allowRefresh && path !== "/auth/refresh") {
    const refreshed = await refreshAuthSession();
    if (refreshed) {
      response = await doFetch(path, init);
    }
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/**
 * Multipart form-data POST with the same auth handling as `request<>()`.
 * Importantly: we do NOT set Content-Type — the browser must add the
 * boundary string itself, otherwise the server can't parse the form.
 */
async function multipartPost<T>(
  path: string,
  formData: FormData,
  allowRefresh = true,
): Promise<T> {
  const init: RequestInit = {
    method: "POST",
    credentials: "include",
    body: formData,
  };
  let response = await fetch(`${API_ROOT}${path}`, init);

  if (response.status === 401 && allowRefresh) {
    const refreshed = await refreshAuthSession();
    if (refreshed) {
      response = await fetch(`${API_ROOT}${path}`, init);
    }
  }
  if (!response.ok) {
    throw await parseError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export type CurrentUserResponse = { id: number; email: string; display_name: string; role: string };

export const apiClient = {
  // allowRefresh=false avoids an infinite loop: if /auth/me returns 401 we
  // don't want to attempt a token refresh (that would also 401, then retry...).
  getMe: () => request<CurrentUserResponse>("/auth/me", undefined, false),
  health: () => request<{ status: string }>("/health"),
  listThreads: () => request<ThreadListResponse>("/threads"),
  getThread: (threadId: string) => request<EmailThread>(`/threads/${threadId}`),
  getQueueSummary: () => request<QueueDashboardResponse>("/queue/summary"),
  startSync: (source = "anywhere", maxResults = 50, lookbackDays = 7) =>
    request<SyncRunStatus>("/sync", {
      method: "POST",
      body: JSON.stringify({
        source,
        max_results: maxResults,
        lookback_days: lookbackDays,
      }),
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
  cancelSyncRun: (runId: number) =>
    request<SyncRunStatus>(`/sync/runs/${runId}/cancel`, {
      method: "POST",
    }),
  saveReview: (threadId: string, payload: Record<string, unknown>) =>
    request<{ status: string }>(`/threads/${threadId}/review`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getContactStats: (range = "all") => request<{
    total: number;
    by_type: Record<string, number>;
    new_per_month: { month: string; count: number }[];
    top_contacts: { email: string; display_name: string; contact_type: string; organization: string; thread_count: number }[];
  }>(`/contacts/stats?range=${encodeURIComponent(range)}`),
  acknowledgeThread: (threadId: string) =>
    request<{ status: string }>(`/threads/${threadId}/acknowledge`, { method: "POST" }),
  acknowledgeBatch: (threadIds: string[]) =>
    request<{ acknowledged: number }>("/inbox/acknowledge-batch", {
      method: "POST",
      body: JSON.stringify({ thread_ids: threadIds }),
    }),
  acknowledgeAll: () =>
    request<{ acknowledged: number }>("/inbox/acknowledge-all", { method: "POST" }),
  analyzeThread: (threadId: string) =>
    request<EmailThread>(`/threads/${threadId}/analyze`, { method: "POST" }),
  markSeen: (threadId: string, seen: boolean) =>
    request<{ status: string }>(`/threads/${threadId}/seen`, {
      method: "POST",
      body: JSON.stringify({ seen }),
    }),
  markPinned: (threadId: string, pinned: boolean) =>
    request<{ status: string }>(`/threads/${threadId}/pin`, {
      method: "POST",
      body: JSON.stringify({ pinned }),
    }),
  getDraft: (threadId: string) =>
    request<DraftDocument | null>(`/threads/${threadId}/draft`),
  generateDraft: (threadId: string, payload: Record<string, unknown>) =>
    request<DraftDocument>(`/threads/${threadId}/draft`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteDraft: (threadId: string) =>
    request<void>(`/threads/${threadId}/draft`, { method: "DELETE" }),
  sendDraft: (threadId: string, payload: { subject: string; body: string; to: string }) =>
    request<{ status: string; message_id: string }>(`/threads/${threadId}/draft/send`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  saveOverride: (threadId: string, payload: ThreadOverrideRequest) =>
    request<ThreadOverride>(`/threads/${threadId}/override`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteOverride: (threadId: string) =>
    request<void>(`/threads/${threadId}/override`, { method: "DELETE" }),
  splitThread: (threadId: string) =>
    request<EmailThread[]>(`/threads/${threadId}/split`, { method: "POST" }),
  getSettings: () => request<SettingsSummary>("/settings"),
  updateSettings: (payload: RuntimeSettingsUpdate) =>
    request<SettingsSummary>("/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  getGmailConnectionStatus: () =>
    request<GmailConnectionStatus>("/gmail/connection"),

  // Knowledge Base
  listKbDocuments: () => request<KbDocumentListResponse>("/knowledge/documents"),
  getKbDocument: (documentId: number) =>
    request<KbDocument>(`/knowledge/documents/${documentId}`),
  listKbChunks: (documentId: number) =>
    request<KbChunkListResponse>(`/knowledge/documents/${documentId}/chunks`),
  updateKbChunk: (
    documentId: number,
    chunkId: number,
    payload: KbChunkUpdateRequest,
  ) =>
    request<KbChunkSummary>(
      `/knowledge/documents/${documentId}/chunks/${chunkId}`,
      { method: "PATCH", body: JSON.stringify(payload) },
    ),
  deleteKbChunk: (documentId: number, chunkId: number) =>
    request<void>(
      `/knowledge/documents/${documentId}/chunks/${chunkId}`,
      { method: "DELETE" },
    ),
  uploadKbDocument: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return multipartPost<KbUploadResponse>("/knowledge/documents", form);
  },
  ingestYouTubeUrl: (url: string) =>
    request<KbUploadResponse>("/knowledge/youtube", {
      method: "POST",
      body: JSON.stringify({ url } satisfies KbYouTubeIngestRequest),
    }),
  finalizeKbDocument: (documentId: number, payload: KbFinalizeRequest) =>
    request<KbDocument>(`/knowledge/documents/${documentId}/finalize`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteKbDocument: (documentId: number) =>
    request<void>(`/knowledge/documents/${documentId}`, { method: "DELETE" }),
  diagnoseRag: (query: string) =>
    request<KbDiagnoseResponse>(
      `/knowledge/diagnose?query=${encodeURIComponent(query)}`,
    ),
};
