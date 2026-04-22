import { useQueryClient } from "@tanstack/react-query";
import {
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Link } from "react-router-dom";

import { ThreadCard } from "../components/ThreadCard";
import { useQueueDashboard, useSyncMutation, useSyncRunStatus } from "../hooks/useApi";
import { formatDate } from "../lib/format";
import type { EmailThread, SyncRunStatus } from "../types/api";

type InboxSection = {
  id: string;
  title: string;
  description: string;
  threads: EmailThread[];
};

type WorkflowBucket = "act-now" | "waiting" | "monitor" | "closed";
type PriorityBrief = {
  threadId: string;
  subject: string;
  summary: string;
  urgency: string;
  nextAction: string;
};

type StageProgressRange = {
  floor: number;
  cap: number;
};

const STAGE_PROGRESS_RANGES: Record<string, StageProgressRange> = {
  queued: { floor: 0, cap: 6 },
  fetching: { floor: 8, cap: 20 },
  persisting: { floor: 22, cap: 40 },
  analyzing: { floor: 42, cap: 88 },
  summarizing: { floor: 90, cap: 97 },
  completed: { floor: 100, cap: 100 },
  failed: { floor: 100, cap: 100 },
};

const STAGE_PROGRESS_DURATIONS_MS: Record<string, number> = {
  queued: 1200,
  fetching: 5200,
  persisting: 4800,
  analyzing: 9000,
  summarizing: 2600,
};

function workflowBucket(thread: EmailThread): WorkflowBucket {
  if (thread.analysis?.needs_action_today) {
    return "act-now";
  }
  if (thread.waiting_on_us) {
    return "waiting";
  }
  if (thread.resolved_or_closed) {
    return "closed";
  }
  return "monitor";
}

function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    queued: "Preparing refresh",
    fetching: "Fetching Gmail",
    persisting: "Grouping threads",
    analyzing: "Analyzing actions",
    summarizing: "Building summary",
    completed: "Completed",
    failed: "Failed",
  };
  return labels[stage] ?? stage;
}

function sectionedThreads(threads: EmailThread[]): InboxSection[] {
  const grouped = {
    "act-now": [] as EmailThread[],
    waiting: [] as EmailThread[],
    monitor: [] as EmailThread[],
    closed: [] as EmailThread[],
  };

  for (const thread of threads) {
    grouped[workflowBucket(thread)].push(thread);
  }

  return [
    {
      id: "act-now",
      title: "Act Now",
      description: "Threads that look urgent or need a reply today.",
      threads: grouped["act-now"],
    },
    {
      id: "waiting",
      title: "Waiting On Us",
      description: "Conversations that need a follow-up, but not necessarily today.",
      threads: grouped.waiting,
    },
    {
      id: "monitor",
      title: "Monitor",
      description: "Keep an eye on these threads, but they are not front-of-queue.",
      threads: grouped.monitor,
    },
    {
      id: "closed",
      title: "Closed Or Low Priority",
      description: "Resolved or low-priority items you likely do not need right now.",
      threads: grouped.closed,
    },
  ];
}

function nextActionThreads(threads: EmailThread[]): EmailThread[] {
  return threads
    .filter(
      (thread) =>
        !thread.resolved_or_closed &&
        Boolean(thread.analysis?.next_action?.trim()),
    )
    .slice(0, 5);
}

function topPriorityBriefs(threads: EmailThread[]): PriorityBrief[] {
  return threads
    .filter(
      (thread) =>
        !thread.resolved_or_closed &&
        Boolean(thread.analysis?.summary?.trim()) &&
        Boolean(thread.analysis?.next_action?.trim()),
    )
    .slice(0, 3)
    .map((thread) => ({
      threadId: thread.thread_id,
      subject: thread.subject || "Untitled thread",
      summary: thread.analysis?.summary ?? "",
      urgency: thread.analysis?.urgency ?? "unknown",
      nextAction: thread.analysis?.next_action ?? "",
    }));
}

function fakeProgressTarget(status: SyncRunStatus | null): number {
  return status ? Math.max(1, status.progress_percent) : 0;
}

function shouldUseTimeBasedSmoothing(stage: string): boolean {
  return stage === "queued" || stage === "fetching" || stage === "summarizing";
}

export function InboxPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQueueDashboard();
  const syncMutation = useSyncMutation();
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [lastHandledRunId, setLastHandledRunId] = useState<number | null>(null);
  const [isSyncSettling, setIsSyncSettling] = useState(false);
  const [displayedProgress, setDisplayedProgress] = useState(0);
  const [stageStartedAt, setStageStartedAt] = useState<number | null>(null);
  const [activeStageKey, setActiveStageKey] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  const syncRunQuery = useSyncRunStatus(activeRunId);
  const syncStatus =
    activeRunId === null
      ? null
      : syncRunQuery.data?.run_id === activeRunId
        ? syncRunQuery.data
        : syncMutation.data?.run_id === activeRunId
          ? syncMutation.data
          : null;

  useEffect(() => {
    if (syncMutation.data?.run_id) {
      setIsSyncSettling(false);
      setActiveRunId(syncMutation.data.run_id);
    }
  }, [syncMutation.data?.run_id]);

  useEffect(() => {
    if (!syncStatus || syncStatus.status !== "running") {
      setStageStartedAt(null);
      setActiveStageKey(null);
      return;
    }

    const nextStageKey = `${syncStatus.run_id}:${syncStatus.stage}`;
    if (nextStageKey === activeStageKey) {
      return;
    }

    setActiveStageKey(nextStageKey);
    setStageStartedAt(Date.now());

    const range = STAGE_PROGRESS_RANGES[syncStatus.stage];
    if (range) {
      setDisplayedProgress((current) =>
        Math.max(current, Math.max(range.floor, syncStatus.progress_percent)),
      );
    }
  }, [activeStageKey, syncStatus]);

  useEffect(() => {
    if (!syncStatus) {
      setDisplayedProgress(0);
      return;
    }

    if (syncStatus.status !== "running") {
      setDisplayedProgress((current) =>
        syncStatus.status === "completed"
          ? Math.max(current, 100)
          : Math.max(current, syncStatus.progress_percent || 100),
      );
      return;
    }

    const range = STAGE_PROGRESS_RANGES[syncStatus.stage] ?? {
      floor: syncStatus.progress_percent,
      cap: syncStatus.progress_percent,
    };
    const duration = STAGE_PROGRESS_DURATIONS_MS[syncStatus.stage] ?? 2600;

    setDisplayedProgress((current) => {
      const floor = Math.max(range.floor, syncStatus.progress_percent);
      if (current <= 0) {
        return floor;
      }
      if (current < floor) {
        return floor;
      }
      if (current > range.cap) {
        return range.cap;
      }
      return current;
    });

    const interval = window.setInterval(() => {
      setDisplayedProgress((current) => {
        const elapsed = stageStartedAt ? Date.now() - stageStartedAt : 0;
        const timeBasedTarget =
          range.floor +
          Math.floor(
            Math.min(1, elapsed / duration) * (range.cap - range.floor),
          );
        const backendTarget = Math.max(range.floor, fakeProgressTarget(syncStatus));
        const target = shouldUseTimeBasedSmoothing(syncStatus.stage)
          ? Math.min(range.cap, Math.max(timeBasedTarget, backendTarget))
          : Math.min(range.cap, backendTarget);

        if (current >= target) {
          return current;
        }

        const remaining = target - current;
        const step = remaining > 14 ? 2 : 1;
        return Math.min(target, current + step);
      });
    }, 160);

    return () => window.clearInterval(interval);
  }, [stageStartedAt, syncStatus]);

  useEffect(() => {
    if (!syncStatus || activeRunId === null) {
      return;
    }

    if (syncStatus.run_id !== activeRunId) {
      return;
    }

    if (syncStatus.status === "running") {
      return;
    }

    if (syncStatus.run_id === lastHandledRunId) {
      return;
    }

    setLastHandledRunId(syncStatus.run_id);
    setIsSyncSettling(true);
    setDisplayedProgress((current) =>
      syncStatus.status === "completed"
        ? Math.max(current, 100)
        : Math.max(current, syncStatus.progress_percent || 100),
    );

    let cancelled = false;

    void (async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
        queryClient.invalidateQueries({ queryKey: ["queue-dashboard"] }),
      ]);

      if (syncStatus.status === "completed") {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
      }

      if (cancelled) {
        return;
      }

      queryClient.removeQueries({ queryKey: ["sync-run", syncStatus.run_id] });
      setStageStartedAt(null);
      setActiveStageKey(null);
      setActiveRunId(null);
      setDisplayedProgress(0);
      setIsSyncSettling(false);
      syncMutation.reset();
    })();

    return () => {
      cancelled = true;
    };
  }, [activeRunId, lastHandledRunId, queryClient, syncMutation, syncStatus]);

  const queueThreads = data?.threads ?? [];
  const filteredThreads = useMemo(() => {
    const term = deferredSearch.trim().toLowerCase();
    if (!term) {
      return queueThreads;
    }
    return queueThreads.filter((thread) =>
      `${thread.subject} ${thread.participants.join(" ")} ${
        thread.analysis?.summary ?? ""
      } ${thread.analysis?.next_action ?? ""}`
        .toLowerCase()
        .includes(term),
    );
  }, [deferredSearch, queueThreads]);

  const sections = useMemo(
    () => sectionedThreads(filteredThreads),
    [filteredThreads],
  );
  const highlightedActions = useMemo(
    () => nextActionThreads(queueThreads),
    [queueThreads],
  );
  const priorityBriefs = useMemo(
    () => topPriorityBriefs(queueThreads),
    [queueThreads],
  );

  const actNowCount = queueThreads.filter(
    (thread) => workflowBucket(thread) === "act-now",
  ).length;
  const waitingCount = queueThreads.filter(
    (thread) => workflowBucket(thread) === "waiting",
  ).length;
  const monitorCount = queueThreads.filter(
    (thread) => workflowBucket(thread) === "monitor",
  ).length;
  const closedCount = queueThreads.filter(
    (thread) => workflowBucket(thread) === "closed",
  ).length;

  const showSyncProgress =
    activeRunId !== null &&
    syncStatus !== null &&
    (syncStatus.status === "running" ||
      syncStatus.status === "completed" ||
      syncStatus.status === "failed" ||
      isSyncSettling);
  const isSyncing = activeRunId !== null && syncStatus?.status === "running";
  const isRefreshLocked = isSyncing || isSyncSettling;
  const hasExistingInboxContent =
    queueThreads.length > 0 ||
    Boolean(data?.summary.executive_summary?.trim()) ||
    priorityBriefs.length > 0;
  const shouldHideInboxContent = showSyncProgress && !hasExistingInboxContent;

  return (
    <section className="page stack stack--page">
      <div className="hero">
        <div>
          <p className="eyebrow">Daily Queue</p>
          <h1>Inbox Command Center</h1>
          <p className="hero-copy">
            Start with what needs action, keep the rest in order, and always
            know the next step.
          </p>
        </div>

        <button
          className="button"
          onClick={() =>
            syncMutation.mutate({ source: "anywhere", maxResults: 50 })
          }
          disabled={syncMutation.isPending || isRefreshLocked}
        >
          {isRefreshLocked ? "Refreshing inbox..." : "Refresh Gmail"}
        </button>
      </div>

      {showSyncProgress && syncStatus ? (
        <section className="panel sync-progress">
          <div className="sync-progress__header">
            <div>
              <p className="eyebrow">Workflow Progress</p>
              <h3>{stageLabel(syncStatus.stage)}</h3>
              <p className="summary-text">
                {syncStatus.status_message || "Refreshing your inbox."}
              </p>
            </div>
            <div className="sync-progress__percent">
              {displayedProgress}%
            </div>
          </div>
          <div aria-hidden="true" className="progress-bar">
            <span style={{ width: `${displayedProgress}%` }} />
          </div>
          <div className="sync-progress__stats">
            <span>{syncStatus.fetched_message_count} messages fetched</span>
            <span>{syncStatus.thread_count} threads grouped</span>
            <span>{syncStatus.ai_thread_count} AI-reviewed</span>
            <span>
              {syncStatus.status === "running"
                ? "Last update: in progress"
                : syncStatus.status === "failed"
                  ? "Last update: failed"
                  : "Last update: applying refresh"}
            </span>
          </div>
          <p className="summary-text">
            {shouldHideInboxContent
              ? "Your inbox will appear once the refresh is fully complete."
              : "Your current inbox stays visible until the new refresh is fully complete."}
          </p>
        </section>
      ) : null}

      {!shouldHideInboxContent ? (
        <>
          <div className="inbox-overview">
            <section className="panel panel--summary panel--summary-rich">
              <p className="eyebrow">What Matters First</p>
              <h3>Priority snapshot</h3>
              <p className="summary-text">
                {data?.summary.executive_summary ??
                  "Run your first refresh to build the inbox summary."}
              </p>
              {priorityBriefs.length ? (
                <ul className="priority-briefs">
                  {priorityBriefs.map((brief) => (
                    <li key={brief.threadId} className="priority-brief">
                      <div className="priority-brief__header">
                        <Link className="priority-brief__title" to={`/threads/${brief.threadId}`}>
                          {brief.subject}
                        </Link>
                        <span className="pill tone-outline">{brief.urgency}</span>
                      </div>
                      <p className="priority-brief__line">
                        <strong>Summary:</strong> {brief.summary}
                      </p>
                      <p className="priority-brief__line">
                        <strong>Next action:</strong> {brief.nextAction}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>

            <section className="panel">
              <p className="eyebrow">Your Next Actions</p>
              <h3>Start here</h3>
              {highlightedActions.length ? (
                <div className="action-list">
                  {highlightedActions.map((thread) => (
                    <Link
                      key={thread.thread_id}
                      className="action-item"
                      to={`/threads/${thread.thread_id}`}
                    >
                      <div>
                        <p className="action-item__title">{thread.subject}</p>
                        <p className="action-item__body">
                          {thread.analysis?.next_action}
                        </p>
                      </div>
                      <span className="pill tone-outline">
                        {thread.analysis?.urgency ?? "unknown"}
                      </span>
                    </Link>
                  ))}
                </div>
              ) : (
                <p className="summary-text">
                  Your next actions will appear here once threads are analyzed.
                </p>
              )}
            </section>
          </div>

          <div className="metric-grid">
            <article className="panel metric-card">
              <p className="eyebrow">Act Now</p>
              <h3>{actNowCount}</h3>
              <p className="summary-text">High-priority threads to handle first.</p>
            </article>
            <article className="panel metric-card">
              <p className="eyebrow">Waiting On Us</p>
              <h3>{waitingCount}</h3>
              <p className="summary-text">Items that need a reply or decision.</p>
            </article>
            <article className="panel metric-card">
              <p className="eyebrow">Monitor</p>
              <h3>{monitorCount}</h3>
              <p className="summary-text">Useful context without immediate action.</p>
            </article>
            <article className="panel metric-card">
              <p className="eyebrow">Closed</p>
              <h3>{closedCount}</h3>
              <p className="summary-text">Resolved or low-priority conversations.</p>
            </article>
          </div>

          <label className="search-bar panel panel--search">
            <span className="eyebrow">Search</span>
            <input
              type="text"
              value={search}
              onChange={(event) =>
                startTransition(() => {
                  setSearch(event.target.value);
                })
              }
              placeholder="Search by subject, participant, summary, or next action"
            />
          </label>
        </>
      ) : null}

      {isLoading ? <p>Loading queue...</p> : null}
      {error instanceof Error ? <p>{error.message}</p> : null}
      {syncMutation.error instanceof Error ? <p>{syncMutation.error.message}</p> : null}
      {syncRunQuery.error instanceof Error ? <p>{syncRunQuery.error.message}</p> : null}

      {!shouldHideInboxContent
        ? sections.map((section) => (
            <section className="thread-section" key={section.id}>
              <div className="thread-section__header">
                <div>
                  <p className="eyebrow">{section.title}</p>
                  <h3>{section.threads.length} thread(s)</h3>
                </div>
                <p className="summary-text">{section.description}</p>
              </div>

              {section.threads.length ? (
                <div className="thread-list">
                  {section.threads.map((thread) => (
                    <ThreadCard key={thread.thread_id} thread={thread} />
                  ))}
                </div>
              ) : (
                <div className="panel thread-section__empty">
                  <p className="summary-text">
                    No threads in this section for the current search.
                  </p>
                </div>
              )}
            </section>
          ))
        : null}
    </section>
  );
}
