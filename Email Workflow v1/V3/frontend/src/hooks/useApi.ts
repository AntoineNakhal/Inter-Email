import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import type {
  EmailThread,
  QueueDashboardResponse,
  SeenState,
  ThreadListResponse,
} from "../types/api";

const LOCAL_CACHE_STALE_MS = 5 * 60 * 1000;
const LOCAL_CACHE_GC_MS = 30 * 60 * 1000;

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
  };
}

function patchThreadSeen(
  thread: EmailThread,
  threadId: string,
  seen: boolean,
): EmailThread {
  if (thread.thread_id !== threadId) return thread;
  return {
    ...thread,
    seen_state: {
      ...buildOptimisticSeenState(thread.seen_state, seen),
      // Marking done also unpins immediately.
      pinned: seen ? false : (thread.seen_state?.pinned ?? false),
    },
    // Marking done clears "act today" immediately — no need to wait for
    // the server round-trip. Undo Done doesn't restore it; the next sync will.
    analysis: thread.analysis && seen
      ? { ...thread.analysis, needs_action_today: false }
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
