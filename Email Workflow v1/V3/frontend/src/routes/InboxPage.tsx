import { useQueryClient } from "@tanstack/react-query";
import { faChevronDown } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link } from "react-router-dom";

import { ThreadCard } from "../components/ThreadCard";

function providerLabel(p: string): string {
  const labels: Record<string, string> = { gmail: "Gmail", outlook: "Outlook", icloud: "iCloud", imap: "IMAP" };
  return labels[p] ?? (p ? p.charAt(0).toUpperCase() + p.slice(1) : "Unknown");
}
import {
  useAcknowledgeAllMutation,
  useAcknowledgeBatchMutation,
  useCancelSyncMutation,
  useQueueDashboard,
  useSyncMutation,
  useSyncRunStatus,
} from "../hooks/useApi";
import { formatDate } from "../lib/format";
import type { EmailThread, SyncRunStatus } from "../types/api";

type InboxSection = {
  id: string;
  title: string;
  description: string;
  threads: EmailThread[];
};

type WorkflowBucket = "act-now" | "waiting" | "monitor" | "low-priority" | "done" | "notifications";
type PriorityFilterValue = "all" | "high" | "medium" | "low" | "unknown";

const UNCATEGORIZED_LABEL = "Needs review";
const PRIORITY_OPTIONS: Array<{
  value: PriorityFilterValue;
  label: string;
}> = [
    { value: "all", label: "All priorities" },
    { value: "high", label: "High" },
    { value: "medium", label: "Medium" },
    { value: "low", label: "Low" },
    { value: "unknown", label: "Unknown" },
  ];
const CATEGORY_ORDER = [
  "Urgent / Executive",
  "Customer / Partner",
  "Events / Logistics",
  "Finance / Admin",
  "FYI / Low Priority",
  "Classified / Sensitive",
  UNCATEGORIZED_LABEL,
];
const SYNC_LOOKBACK_OPTIONS = [
  { days: 7, label: "Last week" },
  { days: 14, label: "Last 2 weeks" },
  { days: 30, label: "Last month" },
  { days: 60, label: "Last 2 months" },
  { days: 90, label: "Last 3 months" },
];

// SOURCE OF TRUTH: how long each stage typically takes. If you measure
// new real-world timings, change ONLY this map — the % ranges below are
// derived from it, so they can never drift out of sync.
function isPinned(thread: EmailThread): boolean {
  return Boolean(thread.seen_state?.pinned);
}

function workflowBucket(thread: EmailThread): WorkflowBucket {
  if (isSeen(thread) || thread.resolved_or_closed) return "done";
  // Service emails always go to notifications — never pollute the action buckets.
  if (thread.is_service_email) return "notifications" as WorkflowBucket;
  if (thread.analysis?.needs_action_today) return "act-now";
  if (thread.waiting_on_us) return "waiting";
  if (thread.relevance_bucket === "noise" || thread.relevance_bucket === "maybe") return "low-priority";
  return "monitor";
}

function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    queued: "Preparing refresh",
    fetching: "Fetching emails",
    persisting: "Grouping threads",
    analyzing: "Analyzing actions",
    summarizing: "Building summary",
    completed: "Completed",
    cancelled: "Cancelled",
    failed: "Failed",
  };
  return labels[stage] ?? stage;
}

function formatEta(ms: number): string {
  const totalSeconds = Math.max(1, Math.ceil(ms / 1000));
  if (totalSeconds < 60) {
    return `~${totalSeconds}s left`;
  }
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return seconds === 0
    ? `~${minutes}m left`
    : `~${minutes}m ${seconds}s left`;
}

function sectionedThreads(threads: EmailThread[]): InboxSection[] {
  const grouped = {
    "act-now": [] as EmailThread[],
    waiting: [] as EmailThread[],
    monitor: [] as EmailThread[],
    "low-priority": [] as EmailThread[],
    done: [] as EmailThread[],
    notifications: [] as EmailThread[],
  };

  for (const thread of threads) {
    grouped[workflowBucket(thread)].push(thread);
  }

  return [
    {
      id: "pinned",
      title: "Pinned",
      description: "Threads you've flagged to keep front-of-mind. Also visible in their original section below.",
      threads: threads.filter(isPinned),
    },
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
      id: "low-priority",
      title: "Low Priority",
      description: "FYI threads and low-signal items. No action needed.",
      threads: grouped["low-priority"],
    },
    {
      id: "done",
      title: "Done",
      description: "Handled threads and resolved conversations. Resurface automatically on new replies.",
      threads: grouped.done,
    },
    {
      id: "notifications",
      title: "Notifications",
      description: "Automated emails from services, apps, and platforms. AI still analyzes these.",
      threads: grouped.notifications,
    },
  ];
}

function isSeen(thread: EmailThread): boolean {
  // Seen-state is versioned by content signature on the backend, so we
  // trust the API's resolved boolean here. If the thread changes later,
  // the backend resets `seen` and it'll re-surface in the hero panels.
  return Boolean(thread.seen_state?.seen);
}


function normalizedUrgency(thread: EmailThread): string {
  return thread.analysis?.urgency ?? "unknown";
}

function normalizedCategory(thread: EmailThread): string {
  return thread.analysis?.category ?? UNCATEGORIZED_LABEL;
}

function SkeletonLine({
  width = "100%",
  className = "",
}: {
  width?: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={`skeleton-line ${className}`.trim()}
      style={{ width }}
    />
  );
}

function ThreadCardSkeleton() {
  return (
    <div aria-hidden="true" className="thread-row thread-row--skeleton">
      <div className="thread-row__link" style={{ pointerEvents: "none" }}>
        <div className="thread-row__top">
          <SkeletonLine className="skeleton-pill" width="72px" />
          <SkeletonLine className="skeleton-line--title" width="42%" />
          <SkeletonLine className="skeleton-pill" width="52px" />
        </div>
        <SkeletonLine width="62%" />
      </div>
    </div>
  );
}

function QueueSkeleton({ refreshing = false }: { refreshing?: boolean }) {
  return (
    <div className="inbox-skeleton stack" aria-hidden="true">
      <section className="thread-section">
        <div className="thread-section__header thread-section__header--act-now">
          <SkeletonLine className="skeleton-line--title" width="72px" />
          <SkeletonLine className="skeleton-pill" width="20px" />
        </div>
        <div className="thread-list">
          {Array.from({ length: refreshing ? 2 : 4 }).map((_, index) => (
            <ThreadCardSkeleton key={index} />
          ))}
        </div>
      </section>

      <section className="thread-section">
        <div className="thread-section__header thread-section__header--waiting">
          <SkeletonLine className="skeleton-line--title" width="108px" />
          <SkeletonLine className="skeleton-pill" width="20px" />
        </div>
        <div className="thread-list">
          {Array.from({ length: 2 }).map((_, index) => (
            <ThreadCardSkeleton key={index} />
          ))}
        </div>
      </section>
    </div>
  );
}

// Per-section default open/closed state. "Act now" and "Waiting on us"
// open by default because that's where the user lands. Everything else
// stays collapsed — context, not action.
const SECTION_DEFAULT_OPEN: Record<string, boolean> = {
  "act-now": true,
  waiting: true,
  monitor: false,
  "low-priority": false,
  done: false,
  notifications: false,
};

type CollapsibleThreadSectionProps = {
  section: InboxSection;
  defaultOpen: boolean;
  newCount?: number;
  compact?: boolean;
};

function CollapsibleThreadSection({
  section,
  defaultOpen,
  newCount = 0,
  compact = false,
}: CollapsibleThreadSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = `thread-section-${section.id}`;
  const acknowledgeBatch = useAcknowledgeBatchMutation();

  return (
    <section className="thread-section">
      {/*
        We keep the existing .thread-section__header div untouched (so its CSS
        layout is preserved) and wrap it in a transparent button that toggles
        `open`. The button strips its native chrome via inline styles so the
        click target visually equals the header, while remaining keyboard-
        accessible and announced as expanded/collapsed by screen readers.
      */}
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-controls={panelId}
        style={{
          display: "block",
          width: "100%",
          background: "transparent",
          border: "none",
          padding: 0,
          margin: 0,
          cursor: "pointer",
          color: "inherit",
          font: "inherit",
          textAlign: "left",
        }}
      >
        <div className={`thread-section__header thread-section__header--${section.id}`}>
          <span className="thread-section__title">{section.title}</span>
          <span className="thread-section__count">{section.threads.length}</span>
          {newCount > 0 && (
            <button
              className="thread-section__new-badge"
              type="button"
              title="Mark section as seen"
              onClick={(e) => {
                e.stopPropagation();
                const ids = section.threads.filter((t) => t.is_new).map((t) => t.thread_id);
                acknowledgeBatch.mutate(ids);
              }}
            >
              {newCount} new
            </button>
          )}
          <span
            aria-hidden="true"
            className="thread-section__chevron"
          >
            <FontAwesomeIcon
              icon={faChevronDown}
              className={open ? "thread-section__chevron-icon thread-section__chevron-icon--open" : "thread-section__chevron-icon"}
            />
            ▾
          </span>
        </div>
      </button>

      {open ? (
        <div id={panelId}>
          {section.threads.length ? (
            <div className="thread-list">
              {section.threads.map((thread) => (
                <ThreadCard key={thread.thread_id} thread={thread} compact={compact} />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function EmptyInboxState({ syncing = false }: { syncing?: boolean }) {
  return (
    <section className="panel empty-state">
      <p className="eyebrow">{syncing ? "Refreshing Inbox" : "Inbox Ready"}</p>
      <h3>{syncing ? "Checking for new email" : "No email in your local inbox yet"}</h3>
      <p className="summary-text">
        {syncing
          ? "We are checking your inboxes now. If nothing new is found, this view will stay empty without a loading skeleton."
          : "Your local queue is currently empty. Refresh Inbox when you want to pull the latest messages into the app."}
      </p>
    </section>
  );
}

function SyncProgressBar({
  label,
  progressPercent,
  isRunning,
  etaSeconds,
  fetchedMessageCount,
  threadCount,
  aiThreadCount,
}: {
  label: string;
  progressPercent: number;
  isRunning: boolean;
  etaSeconds: number | null;
  fetchedMessageCount: number;
  threadCount: number;
  aiThreadCount: number;
}) {
  // The bar position is driven exclusively by the server's progress_percent.
  // A CSS transition handles the smooth movement so we don't need rAF.
  // The ETA label shows exactly what the server computed — no client-side
  // countdown that would drift and jump between polls.
  const displayedPercent = isRunning
    ? Math.max(0, Math.min(99, progressPercent))
    : Math.max(0, Math.min(100, progressPercent));

  const etaLabel =
    etaSeconds !== null && etaSeconds > 0 ? formatEta(etaSeconds * 1000) : null;

  return (
    <div className="sync-bar">
      <div className="sync-bar__top">
        <div className="sync-bar__heading">
          <span className="sync-bar__label">{label}</span>
          {etaLabel ? <span className="sync-bar__eta">{etaLabel}</span> : null}
        </div>
        <span className="sync-bar__percent">{displayedPercent}%</span>
      </div>
      <div className="sync-bar__track" aria-hidden="true">
        <span
          className={`sync-bar__fill ${isRunning ? "sync-bar__fill--running" : ""}`}
          style={{ width: `${displayedPercent}%`, transition: "width 0.9s ease-out" }}
        />
      </div>
      <div className="sync-bar__stats">
        <span>{fetchedMessageCount} messages</span>
        <span>{threadCount} threads</span>
        <span>{aiThreadCount} AI-reviewed</span>
      </div>
    </div>
  );
}

export function InboxPage() {
  const queryClient = useQueryClient();
  const {
    data,
    isLoading,
    error,
    refetch: refetchQueueSummary,
    isFetching: isQueueDashboardFetching,
  } = useQueueDashboard();
  const syncMutation = useSyncMutation();
  const cancelSyncMutation = useCancelSyncMutation();
  const [activeRunId, setActiveRunIdState] = useState<number | null>(() => {
    const stored = sessionStorage.getItem("inter-email.active-run-id");
    return stored ? Number(stored) : null;
  });

  const setActiveRunId = (id: number | null) => {
    setActiveRunIdState(id);
    if (id === null) {
      sessionStorage.removeItem("inter-email.active-run-id");
    } else {
      sessionStorage.setItem("inter-email.active-run-id", String(id));
    }
  };
  const [isSyncSettling, setIsSyncSettling] = useState(false);
  const [search, setSearch] = useState("");
  const [priorityFilter, setPriorityFilter] =
    useState<PriorityFilterValue>("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [accountFilter, setAccountFilter] = useState("all");
  const [syncLookbackDays, setSyncLookbackDays] = useState(7);
  const handledCompletionRunIdRef = useRef<number | null>(null);
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
      handledCompletionRunIdRef.current = null;
      setActiveRunId(syncMutation.data.run_id);
    }
  }, [syncMutation.data?.run_id]);

  // If the stored run ID no longer exists (404 after a DB reset or server
  // restart), clear it so we stop polling and don't block the UI.
  useEffect(() => {
    if (syncRunQuery.error && activeRunId !== null) {
      setActiveRunId(null);
    }
  }, [syncRunQuery.error, activeRunId]);

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

    if (syncStatus.run_id === handledCompletionRunIdRef.current) {
      return;
    }

    handledCompletionRunIdRef.current = syncStatus.run_id;
    setIsSyncSettling(true);

    let cancelled = false;

    // Minimum time the terminal state (100% / cancelled / failed) stays
    // visible after the sync run resolves. This is deliberate UX: the
    // user should clearly see the bar reach its final position before
    // the panel disappears, regardless of how fast the React Query
    // invalidations finish.
    const TERMINAL_HOLD_MS: Record<string, number> = {
      completed: 700,
      cancelled: 600,
      failed: 1200,
    };
    const terminalHoldMs = TERMINAL_HOLD_MS[syncStatus.status] ?? 500;

    void (async () => {
      // Run the query invalidation and the minimum hold in parallel so
      // the bar is guaranteed to be visible for terminalHoldMs even if
      // the network round-trips return faster than that.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
        queryClient.invalidateQueries({ queryKey: ["queue-dashboard"] }),
        new Promise((resolve) => window.setTimeout(resolve, terminalHoldMs)),
      ]);

      if (cancelled) {
        return;
      }

      queryClient.removeQueries({ queryKey: ["sync-run", syncStatus.run_id] });
      setActiveRunId(null);
      setIsSyncSettling(false);
      handledCompletionRunIdRef.current = null;
      syncMutation.reset();
    })();

    return () => {
      cancelled = true;
    };
  }, [activeRunId, queryClient, syncStatus]);

  const queueThreads = data?.threads ?? [];
  const categoryOptions = useMemo(() => {
    const categories = new Set<string>(CATEGORY_ORDER);

    for (const thread of queueThreads) {
      categories.add(normalizedCategory(thread));
    }

    return [...categories].sort((left, right) => {
      const leftIndex = CATEGORY_ORDER.indexOf(left);
      const rightIndex = CATEGORY_ORDER.indexOf(right);

      if (leftIndex === -1 && rightIndex === -1) {
        return left.localeCompare(right);
      }
      if (leftIndex === -1) {
        return 1;
      }
      if (rightIndex === -1) {
        return -1;
      }
      return leftIndex - rightIndex;
    });
  }, [queueThreads]);

  const accountOptions = useMemo(() => {
    const seen = new Set<string>();
    const opts: Array<{ value: string; label: string }> = [{ value: "all", label: "All accounts" }];
    for (const t of queueThreads) {
      const key = t.provider && t.account_email ? `${t.provider}:${t.account_email}` : t.provider || "";
      if (key && !seen.has(key)) {
        seen.add(key);
        const label = t.account_email ? `${providerLabel(t.provider)} – ${t.account_email}` : providerLabel(t.provider);
        opts.push({ value: key, label });
      }
    }
    return opts;
  }, [queueThreads]);

  const filteredThreads = useMemo(() => {
    const term = deferredSearch.trim().toLowerCase();

    return queueThreads.filter((thread) =>
      `${thread.subject} ${thread.participants.join(" ")} ${thread.analysis?.summary ?? ""
        } ${thread.analysis?.next_action ?? ""}`
        .toLowerCase()
        .includes(term) &&
      (priorityFilter === "all" ||
        normalizedUrgency(thread) === priorityFilter) &&
      (categoryFilter === "all" ||
        normalizedCategory(thread) === categoryFilter) &&
      (accountFilter === "all" ||
        (`${thread.provider}:${thread.account_email}` === accountFilter || thread.provider === accountFilter)),
    );
  }, [accountFilter, categoryFilter, deferredSearch, priorityFilter, queueThreads]);

  const sections = useMemo(
    () => sectionedThreads(filteredThreads),
    [filteredThreads],
  );
  const hasActiveFilters =
    deferredSearch.trim().length > 0 ||
    priorityFilter !== "all" ||
    categoryFilter !== "all" ||
    accountFilter !== "all";

  const actNowCount = filteredThreads.filter(
    (thread) => workflowBucket(thread) === "act-now",
  ).length;
  const waitingCount = filteredThreads.filter(
    (thread) => workflowBucket(thread) === "waiting",
  ).length;
  const monitorCount = filteredThreads.filter(
    (thread) => workflowBucket(thread) === "monitor",
  ).length;
  const lowPriorityCount = filteredThreads.filter(
    (thread) => workflowBucket(thread) === "low-priority",
  ).length;
  const doneCount = filteredThreads.filter(
    (thread) => workflowBucket(thread) === "done",
  ).length;
  const pinnedCount = filteredThreads.filter(isPinned).length;
  const totalNewCount = queueThreads.filter((t) => t.is_new).length;
  const acknowledgeAll = useAcknowledgeAllMutation();

  const showSyncProgress =
    activeRunId !== null &&
    syncStatus !== null &&
    (syncStatus.status === "running" ||
      syncStatus.status === "cancelled" ||
      syncStatus.status === "completed" ||
      syncStatus.status === "failed" ||
      isSyncSettling);
  const isSyncing = activeRunId !== null && syncStatus?.status === "running";
  const isCancelling =
    syncStatus?.status === "running" && Boolean(syncStatus.cancellation_requested);
  const isRefreshLocked = isSyncing || isSyncSettling || isCancelling;
  const hasExistingInboxContent =
    queueThreads.length > 0 ||
    Boolean(data?.summary.executive_summary?.trim());
  const hasSyncActivity =
    (syncStatus?.fetched_message_count ?? 0) > 0 ||
    (syncStatus?.thread_count ?? 0) > 0 ||
    (syncStatus?.ai_thread_count ?? 0) > 0;
  const showInitialSkeleton = isLoading && !data;
  const showRefreshSkeleton =
    isSyncing && !hasExistingInboxContent && hasSyncActivity;
  const canRenderInboxShell = !showInitialSkeleton && !showRefreshSkeleton;
  const showEmptyState =
    canRenderInboxShell &&
    queueThreads.length === 0 &&
    !data?.summary.executive_summary?.trim();
  const shouldRenderInboxContent = canRenderInboxShell && !showEmptyState;
  const triggerRefresh = () => {
    if (isRefreshLocked) {
      return;
    }

    syncMutation.mutate({
      source: "anywhere",
      maxResults: 50,
      lookbackDays: syncLookbackDays,
    });
  };

  return (
    <section className="page page--inbox stack stack--page">
      <div className="sp-header inbox-page__header">
        <div className="sp-header__left inbox-page__header-copy">
          <p className="sp-header__eyebrow">
            Daily Queue · {new Date().toLocaleDateString("en-CA", { weekday: "short", month: "short", day: "numeric" })}
          </p>
          <h1 className="sp-header__title">Inbox</h1>
          {queueThreads.length > 0 && (
            <div className="inbox-header__stats">
              {actNowCount > 0 && <span className="inbox-header__stat inbox-header__stat--urgent">{actNowCount} act now</span>}
              {waitingCount > 0 && <span className="inbox-header__stat inbox-header__stat--watch">{waitingCount} waiting</span>}
              {pinnedCount > 0 && <span className="inbox-header__stat inbox-header__stat--pinned">{pinnedCount} pinned</span>}
              <span className="inbox-header__stat">{queueThreads.length} total</span>
              {totalNewCount > 0 && (
                <button
                  className="inbox-header__see-all"
                  type="button"
                  onClick={() => acknowledgeAll.mutate()}
                  disabled={acknowledgeAll.isPending}
                  title={`Mark all ${totalNewCount} new emails as seen`}
                >
                  See all ({totalNewCount} new)
                </button>
              )}
            </div>
          )}
          {isLoading && !data ? (
            <div className="inbox-header__summary-skeleton">
              <SkeletonLine width="72%" />
              <SkeletonLine width="52%" />
            </div>
          ) : data?.summary.executive_summary?.trim() ? (
            <p className="sp-header__sub">{data.summary.executive_summary}</p>
          ) : null}
        </div>

        <div className="inbox-header__actions">
          <select
            id="sync-lookback-days"
            value={syncLookbackDays}
            onChange={(event) => setSyncLookbackDays(Number(event.target.value))}
            disabled={syncMutation.isPending || isRefreshLocked}
          >
            {SYNC_LOOKBACK_OPTIONS.map((option) => (
              <option key={option.days} value={option.days}>{option.label}</option>
            ))}
          </select>
          <button
            type="button"
            className={`inbox-header__btn ${isSyncing ? "inbox-header__btn--danger" : ""}`}
            onClick={() => {
              if (isSyncing && activeRunId !== null && !isCancelling) {
                cancelSyncMutation.mutate(activeRunId);
                return;
              }
              triggerRefresh();
            }}
            disabled={
              syncMutation.isPending ||
              cancelSyncMutation.isPending ||
              isCancelling ||
              (isSyncSettling && !isSyncing)
            }
          >
            {isCancelling || cancelSyncMutation.isPending
              ? "Cancelling..."
              : isSyncing
                ? "Cancel refresh"
                : isSyncSettling
                  ? "Refreshing inbox..."
                  : "Refresh Inbox"}
          </button>
        </div>
      </div>
      {showSyncProgress && syncStatus ? (
        <>
          <div className="sp-divider" />
          <SyncProgressBar
            label={syncStatus.status_message || stageLabel(syncStatus.stage)}
            progressPercent={syncStatus.progress_percent}
            isRunning={syncStatus.status === "running"}
            etaSeconds={syncStatus.eta_seconds}
            fetchedMessageCount={syncStatus.fetched_message_count}
            threadCount={syncStatus.thread_count}
            aiThreadCount={syncStatus.ai_thread_count}
          />
        </>
      ) : null}

      <div className="sp-divider" />

      <div className="inbox-toolbar">
          <input
            type="text"
            className="inbox-toolbar__search"
            value={search}
            onChange={(event) =>
              startTransition(() => setSearch(event.target.value))
            }
            placeholder="Search threads…"
          />
          <div className="inbox-toolbar__filters">
            <label className="select-field">
              <select
                value={categoryFilter}
                onChange={(event) => setCategoryFilter(event.target.value)}
              >
                <option value="all">All categories</option>
                {categoryOptions.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
              <FontAwesomeIcon icon={faChevronDown} className="select-field__icon" />
            </label>
            <label className="select-field">
              <select
                value={priorityFilter}
                onChange={(event) =>
                  setPriorityFilter(event.target.value as PriorityFilterValue)
                }
              >
                {PRIORITY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <FontAwesomeIcon icon={faChevronDown} className="select-field__icon" />
            </label>
            {accountOptions.length > 1 && (
              <label className="select-field">
                <select value={accountFilter} onChange={e => setAccountFilter(e.target.value)}>
                  {accountOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                <FontAwesomeIcon icon={faChevronDown} className="select-field__icon" />
              </label>
            )}
            <button
              className={`inbox-toolbar__clear${hasActiveFilters ? "" : " inbox-toolbar__clear--inactive"}`}
              type="button"
              tabIndex={hasActiveFilters ? 0 : -1}
              onClick={() => {
                if (!hasActiveFilters) return;
                setSearch("");
                setPriorityFilter("all");
                setCategoryFilter("all");
                setAccountFilter("all");
              }}
            >
              Clear
            </button>
          </div>
        </div>
      <div className="sp-divider" />


      {showInitialSkeleton ? <QueueSkeleton /> : null}
      {showRefreshSkeleton ? <QueueSkeleton refreshing /> : null}
      {showEmptyState ? <EmptyInboxState syncing={isSyncing} /> : null}

      {error instanceof Error ? <p>{error.message}</p> : null}
      {syncMutation.error instanceof Error ? <p>{syncMutation.error.message}</p> : null}
      {syncRunQuery.error instanceof Error ? <p>{syncRunQuery.error.message}</p> : null}

      {shouldRenderInboxContent
        ? sections.map((section) => (
          <CollapsibleThreadSection
            key={section.id}
            section={section}
            defaultOpen={SECTION_DEFAULT_OPEN[section.id] ?? true}
            newCount={section.threads.filter((t) => t.is_new).length}
            compact={section.id === "notifications"}
          />
        ))
        : null}
    </section>
  );
}
