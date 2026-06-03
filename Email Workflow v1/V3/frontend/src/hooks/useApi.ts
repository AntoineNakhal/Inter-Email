import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, type CurrentUserResponse } from "../api/client";
import type {
  EmailThread,
  QueueDashboardResponse,
  SeenState,
  ThreadListResponse,
  ThreadOverrideRequest,
} from "../types/api";

const LOCAL_CACHE_STALE_MS = 5 * 60 * 1000;
const LOCAL_CACHE_GC_MS = 30 * 60 * 1000;

/**
 * Checks whether the user has an active session. Returns the user object when
 * authenticated, `null` when definitely not (401), or `undefined` while loading.
 * No other hook should fire data requests until this resolves to a user object.
 */
export function useCurrentUser(): { user: CurrentUserResponse | null; isLoading: boolean } {
  const { data, isLoading, isFetching } = useQuery<CurrentUserResponse | null>({
    queryKey: ["current-user"],
    queryFn: async () => {
      try {
        return await apiClient.getMe();
      } catch {
        // Any error (401, network, etc.) means "not authenticated" for our purposes.
        return null;
      }
    },
    staleTime: LOCAL_CACHE_STALE_MS,
    gcTime: LOCAL_CACHE_GC_MS,
    retry: false, // don't hammer /auth/me on failure
    refetchOnWindowFocus: false,
  });
  // Include isFetching so AppShell waits for background refetches to complete
  // before deciding to redirect. Without this, a stale null cache causes an
  // immediate redirect to /login right after a successful login (race condition).
  return { user: data ?? null, isLoading: isLoading || isFetching };
}

export function useThreads() {
  return useQuery({
    queryKey: ["threads"],
    queryFn: apiClient.listThreads,
    staleTime: LOCAL_CACHE_STALE_MS,
    gcTime: LOCAL_CACHE_GC_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export function useQueueDashboard() {
  return useQuery({
    queryKey: ["queue-dashboard"],
    queryFn: apiClient.getQueueSummary,
    staleTime: LOCAL_CACHE_STALE_MS,
    gcTime: LOCAL_CACHE_GC_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export function useLatestSyncRunStatus() {
  return useQuery({
    queryKey: ["sync-run", "latest"],
    queryFn: apiClient.getLatestSyncRunStatus,
  });
}

export function useSyncRunStatus(runId: number | null) {
  return useQuery({
    queryKey: ["sync-run", runId],
    queryFn: () => apiClient.getSyncRunStatus(runId ?? 0),
    enabled: runId !== null,
    retry: false, // a 404 (stale run after DB reset) should not be retried
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 1000 : false,
  });
}

export function useThread(threadId: string | undefined) {
  return useQuery({
    queryKey: ["thread", threadId],
    queryFn: () => apiClient.getThread(threadId ?? ""),
    enabled: Boolean(threadId),
    staleTime: LOCAL_CACHE_STALE_MS,
    gcTime: LOCAL_CACHE_GC_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: apiClient.getSettings,
    staleTime: LOCAL_CACHE_STALE_MS,
    gcTime: LOCAL_CACHE_GC_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export function useUpdateSettingsMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: apiClient.updateSettings,
    onSuccess: async (settings) => {
      queryClient.setQueryData(["settings"], settings);
    },
  });
}

export function useGmailConnectionStatus() {
  return useQuery({
    queryKey: ["gmail-connection-status"],
    queryFn: apiClient.getGmailConnectionStatus,
    staleTime: LOCAL_CACHE_STALE_MS,
    gcTime: LOCAL_CACHE_GC_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export function useSyncMutation() {
  return useMutation({
    mutationFn: ({
      source,
      maxResults,
      lookbackDays,
    }: {
      source: string;
      maxResults: number;
      lookbackDays: number;
    }) => apiClient.startSync(source, maxResults, lookbackDays),
  });
}

export function useCancelSyncMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: number) => apiClient.cancelSyncRun(runId),
    onSuccess: async (result) => {
      queryClient.setQueryData(["sync-run", result.run_id], result);
      queryClient.setQueryData(["sync-run", "latest"], result);
    },
  });
}

export function useReviewMutation(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      apiClient.saveReview(threadId, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
        queryClient.invalidateQueries({ queryKey: ["thread", threadId] }),
      ]);
    },
  });
}

// Build an optimistic SeenState. The backend will recompute seen_version /
// seen_at on its next read, but for the immediate UI flip we keep the prior
// version string (or empty if absent) and stamp the timestamp now.
function buildOptimisticSeenState(prior: SeenState | null, seen: boolean): SeenState {
  return {
    seen,
    seen_version: prior?.seen_version ?? "",
    seen_at: seen ? new Date().toISOString() : null,
    pinned: prior?.pinned ?? false,
  };
}

function patchThreadAcknowledged(
  thread: EmailThread,
  threadId?: string,
): EmailThread {
  if (threadId && thread.thread_id !== threadId) return thread;
  if (!thread.is_new) return thread;
  return {
    ...thread,
    is_new: false,
  };
}

function patchThreadSeen(
  thread: EmailThread,
  threadId: string,
  seen: boolean,
): EmailThread {
  if (thread.thread_id !== threadId) return thread;
  const optimisticSeenState = buildOptimisticSeenState(thread.seen_state, seen);
  return {
    ...thread,
    is_new: false,
    seen_state: {
      ...optimisticSeenState,
      pinned: seen ? false : optimisticSeenState.pinned,
    },
    // Marking done clears "act today" immediately — no need to wait for
    // the server round-trip. Undo Done doesn't restore it; the next sync will.
    analysis: thread.analysis && seen
      ? { ...thread.analysis, needs_action_today: false, needs_next_action: false }
      : thread.analysis,
  };
}

function patchThreadPinned(
  thread: EmailThread,
  threadId: string,
  pinned: boolean,
): EmailThread {
  if (thread.thread_id !== threadId) return thread;
  return {
    ...thread,
    is_new: false,
    seen_state: thread.seen_state
      ? { ...thread.seen_state, pinned }
      : { seen: false, seen_version: "", seen_at: null, pinned },
  };
}

type SeenMutationContext = {
  previousThreads: ThreadListResponse | undefined;
  previousQueue: QueueDashboardResponse | undefined;
  previousThread: EmailThread | undefined;
};

export function useSeenMutation(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, boolean, SeenMutationContext>({
    mutationFn: (seen: boolean) => apiClient.markSeen(threadId, seen),

    // Optimistic update: patch the cached threads/queue/thread payloads
    // immediately so the inbox reflects the change with zero network wait.
    // We snapshot the prior state and return it as context so onError can
    // roll back cleanly if the server rejects the mutation.
    onMutate: async (seen) => {
      // Cancel any in-flight refetches that would clobber our optimistic
      // write before the mutation resolves.
      await Promise.all([
        queryClient.cancelQueries({ queryKey: ["threads"] }),
        queryClient.cancelQueries({ queryKey: ["queue-dashboard"] }),
        queryClient.cancelQueries({ queryKey: ["thread", threadId] }),
      ]);

      const previousThreads = queryClient.getQueryData<ThreadListResponse>([
        "threads",
      ]);
      const previousQueue = queryClient.getQueryData<QueueDashboardResponse>([
        "queue-dashboard",
      ]);
      const previousThread = queryClient.getQueryData<EmailThread>([
        "thread",
        threadId,
      ]);

      if (previousThreads) {
        queryClient.setQueryData<ThreadListResponse>(["threads"], {
          ...previousThreads,
          threads: previousThreads.threads.map((thread) =>
            patchThreadSeen(thread, threadId, seen),
          ),
        });
      }

      if (previousQueue) {
        queryClient.setQueryData<QueueDashboardResponse>(["queue-dashboard"], {
          ...previousQueue,
          threads: previousQueue.threads.map((thread) =>
            patchThreadSeen(thread, threadId, seen),
          ),
        });
      }

      if (previousThread) {
        queryClient.setQueryData<EmailThread>(
          ["thread", threadId],
          patchThreadSeen(previousThread, threadId, seen),
        );
      }

      return { previousThreads, previousQueue, previousThread };
    },

    onError: (_error, _seen, context) => {
      // Roll back to the snapshot taken in onMutate.
      if (context?.previousThreads !== undefined) {
        queryClient.setQueryData(["threads"], context.previousThreads);
      }
      if (context?.previousQueue !== undefined) {
        queryClient.setQueryData(["queue-dashboard"], context.previousQueue);
      }
      if (context?.previousThread !== undefined) {
        queryClient.setQueryData(["thread", threadId], context.previousThread);
      }
    },

    // Refetch on settle (success OR error) so the cache stays consistent
    // with the server's authoritative seen_version / seen_at values.
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
        queryClient.invalidateQueries({ queryKey: ["queue-dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["thread", threadId] }),
      ]);
    },
  });
}

export function useContactStats(range = "all") {
  return useQuery({
    queryKey: ["contact-stats", range],
    queryFn: () => apiClient.getContactStats(range),
    staleTime: LOCAL_CACHE_STALE_MS,
    gcTime: LOCAL_CACHE_GC_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export function useAcknowledgeBatchMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (threadIds: string[]) => apiClient.acknowledgeBatch(threadIds),
    onMutate: async (threadIds) => {
      const idSet = new Set(threadIds);
      await Promise.all([
        queryClient.cancelQueries({ queryKey: ["queue-dashboard"] }),
        queryClient.cancelQueries({ queryKey: ["threads"] }),
      ]);
      const prevDashboard = queryClient.getQueryData<QueueDashboardResponse>(["queue-dashboard"]);
      const prevThreads = queryClient.getQueryData<ThreadListResponse>(["threads"]);
      if (prevDashboard) {
        queryClient.setQueryData<QueueDashboardResponse>(["queue-dashboard"], {
          ...prevDashboard,
          threads: prevDashboard.threads.map((t) =>
            idSet.has(t.thread_id) ? { ...t, is_new: false } : t
          ),
        });
      }
      if (prevThreads) {
        queryClient.setQueryData<ThreadListResponse>(["threads"], {
          ...prevThreads,
          threads: prevThreads.threads.map((t) =>
            idSet.has(t.thread_id) ? { ...t, is_new: false } : t
          ),
        });
      }
      return { prevDashboard, prevThreads };
    },
    onError: (_err, _ids, ctx) => {
      if (ctx?.prevDashboard) queryClient.setQueryData(["queue-dashboard"], ctx.prevDashboard);
      if (ctx?.prevThreads) queryClient.setQueryData(["threads"], ctx.prevThreads);
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["queue-dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
      ]);
    },
  });
}

export function useAcknowledgeAllMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiClient.acknowledgeAll(),
    onMutate: async () => {
      await Promise.all([
        queryClient.cancelQueries({ queryKey: ["queue-dashboard"] }),
        queryClient.cancelQueries({ queryKey: ["threads"] }),
      ]);
      const prevDashboard = queryClient.getQueryData<QueueDashboardResponse>(["queue-dashboard"]);
      const prevThreads = queryClient.getQueryData<ThreadListResponse>(["threads"]);
      if (prevDashboard) {
        queryClient.setQueryData<QueueDashboardResponse>(["queue-dashboard"], {
          ...prevDashboard,
          threads: prevDashboard.threads.map((t) => ({ ...t, is_new: false })),
        });
      }
      if (prevThreads) {
        queryClient.setQueryData<ThreadListResponse>(["threads"], {
          ...prevThreads,
          threads: prevThreads.threads.map((t) => ({ ...t, is_new: false })),
        });
      }
      return { prevDashboard, prevThreads };
    },
    onError: (_err, _v, ctx) => {
      if (ctx?.prevDashboard) queryClient.setQueryData(["queue-dashboard"], ctx.prevDashboard);
      if (ctx?.prevThreads) queryClient.setQueryData(["threads"], ctx.prevThreads);
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["queue-dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
      ]);
    },
  });
}

export function useAcknowledgeThreadMutation(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiClient.acknowledgeThread(threadId),
    onSuccess: async () => {
      const previousThreads =
        queryClient.getQueryData<ThreadListResponse>(["threads"]);
      const previousQueue =
        queryClient.getQueryData<QueueDashboardResponse>(["queue-dashboard"]);
      const previousThread =
        queryClient.getQueryData<EmailThread>(["thread", threadId]);

      if (previousThreads) {
        queryClient.setQueryData<ThreadListResponse>(["threads"], {
          ...previousThreads,
          threads: previousThreads.threads.map((thread) =>
            patchThreadAcknowledged(thread, threadId),
          ),
        });
      }

      if (previousQueue) {
        queryClient.setQueryData<QueueDashboardResponse>(["queue-dashboard"], {
          ...previousQueue,
          threads: previousQueue.threads.map((thread) =>
            patchThreadAcknowledged(thread, threadId),
          ),
        });
      }

      if (previousThread) {
        queryClient.setQueryData<EmailThread>(
          ["thread", threadId],
          patchThreadAcknowledged(previousThread, threadId),
        );
      }

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["queue-dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
        queryClient.invalidateQueries({ queryKey: ["thread", threadId] }),
      ]);
    },
  });
}

export function useAnalyzeMutation(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiClient.analyzeThread(threadId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["thread", threadId] }),
        queryClient.invalidateQueries({ queryKey: ["queue-dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
      ]);
    },
  });
}

export function usePinMutation(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, boolean, SeenMutationContext>({
    mutationFn: (pinned: boolean) => apiClient.markPinned(threadId, pinned),
    onMutate: async (pinned) => {
      await Promise.all([
        queryClient.cancelQueries({ queryKey: ["threads"] }),
        queryClient.cancelQueries({ queryKey: ["queue-dashboard"] }),
        queryClient.cancelQueries({ queryKey: ["thread", threadId] }),
      ]);
      const previousThreads = queryClient.getQueryData<ThreadListResponse>(["threads"]);
      const previousQueue = queryClient.getQueryData<QueueDashboardResponse>(["queue-dashboard"]);
      const previousThread = queryClient.getQueryData<EmailThread>(["thread", threadId]);
      if (previousThreads) {
        queryClient.setQueryData<ThreadListResponse>(["threads"], {
          ...previousThreads,
          threads: previousThreads.threads.map((t) => patchThreadPinned(t, threadId, pinned)),
        });
      }
      if (previousQueue) {
        queryClient.setQueryData<QueueDashboardResponse>(["queue-dashboard"], {
          ...previousQueue,
          threads: previousQueue.threads.map((t) => patchThreadPinned(t, threadId, pinned)),
        });
      }
      if (previousThread) {
        queryClient.setQueryData<EmailThread>(
          ["thread", threadId],
          patchThreadPinned(previousThread, threadId, pinned),
        );
      }
      return { previousThreads, previousQueue, previousThread };
    },
    onError: (_error, _pinned, context) => {
      if (context?.previousThreads !== undefined) {
        queryClient.setQueryData(["threads"], context.previousThreads);
      }
      if (context?.previousQueue !== undefined) {
        queryClient.setQueryData(["queue-dashboard"], context.previousQueue);
      }
      if (context?.previousThread !== undefined) {
        queryClient.setQueryData(["thread", threadId], context.previousThread);
      }
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
        queryClient.invalidateQueries({ queryKey: ["queue-dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["thread", threadId] }),
      ]);
    },
  });
}

export function useSaveOverrideMutation(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ThreadOverrideRequest) =>
      apiClient.saveOverride(threadId, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["thread", threadId] }),
        queryClient.invalidateQueries({ queryKey: ["queue-dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
      ]);
    },
  });
}

export function useDeleteOverrideMutation(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiClient.deleteOverride(threadId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["thread", threadId] }),
        queryClient.invalidateQueries({ queryKey: ["queue-dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
      ]);
    },
  });
}

export function useSplitThreadMutation(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiClient.splitThread(threadId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
        queryClient.invalidateQueries({ queryKey: ["queue-dashboard"] }),
      ]);
    },
  });
}

export function useDraftMutation(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      apiClient.generateDraft(threadId, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["thread", threadId] }),
      ]);
    },
  });
}

export function useDeleteDraftMutation(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiClient.deleteDraft(threadId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["thread", threadId] }),
        queryClient.invalidateQueries({ queryKey: ["queue-dashboard"] }),
      ]);
    },
  });
}

// ─── Knowledge Base ──────────────────────────────────────────────────────
const KB_DOCUMENTS_KEY = ["kb-documents"] as const;
const KB_DOCUMENT_KEY = (id: number) => ["kb-document", id] as const;

/**
 * Lists KB documents. Polls every 4 seconds while any doc is still
 * processing so the UI updates without manual refresh — once everything
 * is in a terminal state (awaiting_review / ready / failed) we drop back
 * to a passive cache.
 */
export function useKbDocuments() {
  return useQuery({
    queryKey: KB_DOCUMENTS_KEY,
    queryFn: apiClient.listKbDocuments,
    staleTime: LOCAL_CACHE_STALE_MS,
    gcTime: LOCAL_CACHE_GC_MS,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const hasInflight = data.documents.some(
        (doc) => doc.status === "pending" || doc.status === "processing",
      );
      return hasInflight ? 4000 : false;
    },
  });
}

/**
 * Lists every chunk for a document — used by the modal's chunk explorer.
 * Only fires once the doc is past PROCESSING (no point asking earlier
 * because chunks haven't been written yet).
 */
export function useKbChunks(
  documentId: number | null,
  shouldFetch: boolean,
) {
  return useQuery({
    queryKey: documentId
      ? (["kb-chunks", documentId] as const)
      : (["kb-chunks", "none"] as const),
    queryFn: () => apiClient.listKbChunks(documentId as number),
    enabled: documentId !== null && shouldFetch,
    staleTime: LOCAL_CACHE_STALE_MS,
    refetchOnWindowFocus: false,
  });
}

/**
 * Polls a single document while it's still pre-review so the modal can
 * update its UI as soon as the worker finishes. Stops polling once the
 * doc reaches a terminal state.
 */
export function useKbDocument(documentId: number | null) {
  return useQuery({
    queryKey: documentId ? KB_DOCUMENT_KEY(documentId) : ["kb-document", "none"],
    queryFn: () => apiClient.getKbDocument(documentId as number),
    enabled: documentId !== null,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 1500;
      // Keep polling while the worker is still doing its thing.
      return data.status === "pending" || data.status === "processing"
        ? 1500
        : false;
    },
    refetchOnWindowFocus: false,
  });
}

export function useUploadKbDocumentMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => apiClient.uploadKbDocument(file),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: KB_DOCUMENTS_KEY });
    },
  });
}

export function useIngestYouTubeMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (url: string) => apiClient.ingestYouTubeUrl(url),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: KB_DOCUMENTS_KEY });
    },
  });
}

export function useFinalizeKbDocumentMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      documentId,
      payload,
    }: {
      documentId: number;
      payload: import("../types/api").KbFinalizeRequest;
    }) => apiClient.finalizeKbDocument(documentId, payload),
    onSuccess: async (_data, { documentId }) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: KB_DOCUMENTS_KEY }),
        queryClient.invalidateQueries({ queryKey: KB_DOCUMENT_KEY(documentId) }),
      ]);
    },
  });
}

export function useDeleteKbDocumentMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (documentId: number) => apiClient.deleteKbDocument(documentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: KB_DOCUMENTS_KEY });
    },
  });
}

export function useUpdateKbChunkMutation(documentId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ chunkId, content }: { chunkId: number; content: string }) =>
      apiClient.updateKbChunk(documentId, chunkId, { content }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["kb-chunks", documentId],
      });
    },
  });
}

export function useDeleteKbChunkMutation(documentId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (chunkId: number) =>
      apiClient.deleteKbChunk(documentId, chunkId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["kb-chunks", documentId] }),
        queryClient.invalidateQueries({ queryKey: KB_DOCUMENTS_KEY }),
      ]);
    },
  });
}
