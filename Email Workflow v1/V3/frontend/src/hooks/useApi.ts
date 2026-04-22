import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../api/client";

export function useThreads() {
  return useQuery({
    queryKey: ["threads"],
    queryFn: apiClient.listThreads,
  });
}

export function useQueueDashboard() {
  return useQuery({
    queryKey: ["queue-dashboard"],
    queryFn: apiClient.getQueueSummary,
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
  });
}

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: apiClient.getSettings,
  });
}

export function useUpdateSettingsMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: apiClient.updateSettings,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });
}

export function useGmailConnectionStatus() {
  return useQuery({
    queryKey: ["gmail-connection-status"],
    queryFn: apiClient.getGmailConnectionStatus,
  });
}

export function useSyncMutation() {
  return useMutation({
    mutationFn: ({ source, maxResults }: { source: string; maxResults: number }) =>
      apiClient.startSync(source, maxResults),
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

export function useSeenMutation(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (seen: boolean) => apiClient.markSeen(threadId, seen),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
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
