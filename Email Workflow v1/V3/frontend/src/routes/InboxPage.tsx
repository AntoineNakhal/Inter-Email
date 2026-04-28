import { useQueryClient } from "@tanstack/react-query";
import {
  faArrowLeft,
  faArrowUpRightFromSquare,
  faArrowRight,
  faChevronDown,
  faSquareCheck,
  faThumbtack,
  faXmark,
} from "@fortawesome/free-solid-svg-icons";
import { faSquare } from "@fortawesome/free-regular-svg-icons";
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
import { DraftComposer } from "../features/drafts/DraftComposer";
import {
  useCancelSyncMutation,
  usePinMutation,
  useQueueDashboard,
  useSeenMutation,
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

type WorkflowBucket = "act-now" | "waiting" | "monitor" | "low-priority" | "done";
type PriorityFilterValue = "all" | "high" | "medium" | "low" | "unknown";

type StageProgressRange = {
  floor: number;
  cap: number;
};

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
const STAGE_PROGRESS_DURATIONS_MS: Record<string, number> = {
  queued: 1200,
  fetching: 5200,
  persisting: 4800,
  analyzing: 9000,
  summarizing: 2600,
};

// The order in which stages run. Used to compute cumulative % ranges.
const STAGE_ORDER: ReadonlyArray<string> = [
  "queued",
  "fetching",
  "persisting",
  "analyzing",
  "summarizing",
];

/**
 * Derive `{ floor, cap }` ranges for each stage from its duration share.
 * Each stage's width is proportional to its duration / total duration, so
 * the % bar tracks elapsed time. A small gap is inserted between stages
 * (visual signal of stage transition) and before 100 (so completion is
 * its own visible jump).
 */
function buildStageProgressRanges(
  order: ReadonlyArray<string>,
  durations: Record<string, number>,
  options: { interStageGap?: number; completionGap?: number } = {},
): Record<string, StageProgressRange> {
  const interStageGap = options.interStageGap ?? 1;
  const completionGap = options.completionGap ?? 3;
  const totalDuration = order.reduce(
    (sum, stage) => sum + (durations[stage] ?? 0),
    0,
  );
  const usableBudget = Math.max(
    0,
    100 - completionGap - interStageGap * Math.max(0, order.length - 1),
  );

  const ranges: Record<string, StageProgressRange> = {};
  let cursor = 0;
  for (let i = 0; i < order.length; i += 1) {
    const stage = order[i];
    const share =
      totalDuration > 0
        ? (durations[stage] ?? 0) / totalDuration
        : 1 / order.length;
    const width = Math.round(share * usableBudget);
    const floor = cursor;
    const cap = Math.min(100 - completionGap, floor + width);
    ranges[stage] = { floor, cap };
    cursor = cap + interStageGap;
  }

  ranges.completed = { floor: 100, cap: 100 };
  ranges.failed = { floor: 100, cap: 100 };
  return ranges;
}

const STAGE_PROGRESS_RANGES: Record<string, StageProgressRange> =
  buildStageProgressRanges(STAGE_ORDER, STAGE_PROGRESS_DURATIONS_MS);

function isPinned(thread: EmailThread): boolean {
  return Boolean(thread.seen_state?.pinned);
}

function workflowBucket(thread: EmailThread): WorkflowBucket {
  if (isSeen(thread) || thread.resolved_or_closed) return "done";
  if (thread.analysis?.needs_action_today) return "act-now";
  if (thread.waiting_on_us) return "waiting";
  if (thread.relevance_bucket === "noise" || thread.relevance_bucket === "maybe") return "low-priority";
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
    cancelled: "Cancelled",
    failed: "Failed",
  };
  return labels[stage] ?? stage;
}

function sectionedThreads(threads: EmailThread[]): InboxSection[] {
  const grouped = {
    "act-now": [] as EmailThread[],
    waiting: [] as EmailThread[],
    monitor: [] as EmailThread[],
    "low-priority": [] as EmailThread[],
    done: [] as EmailThread[],
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
  ];
}

function isSeen(thread: EmailThread): boolean {
  // Seen-state is versioned by content signature on the backend, so we
  // trust the API's resolved boolean here. If the thread changes later,
  // the backend resets `seen` and it'll re-surface in the hero panels.
  return Boolean(thread.seen_state?.seen);
}

function priorityRank(thread: EmailThread): number {
  let score = 0;
  if (thread.analysis?.needs_action_today) score += 100;
  if (thread.seen_state?.pinned) score += 50;
  if (thread.analysis?.urgency === "high") score += 30;
  score += Math.min(thread.message_count, 12);
  return score;
}

function topPriorityThreads(threads: EmailThread[]): EmailThread[] {
  return [...threads]
    .filter(
      (thread) =>
        !thread.resolved_or_closed &&
        !isSeen(thread) &&
        Boolean(thread.analysis?.next_action?.trim()) &&
        (
          Boolean(thread.analysis?.needs_action_today) ||
          thread.analysis?.urgency === "high" ||
          Boolean(thread.seen_state?.pinned)
        ),
    )
    .sort((left, right) => priorityRank(right) - priorityRank(left))
    .slice(0, 6);
}

function priorityWorkflowLabel(thread: EmailThread): string {
  if (thread.analysis?.needs_action_today) return "Act today";
  if (thread.waiting_on_us) return "Waiting on us";
  if (thread.resolved_or_closed) return "Closed";
  return "Monitor";
}

function priorityWorkflowTone(thread: EmailThread): string {
  if (thread.analysis?.needs_action_today) return "tone-urgent";
  if (thread.waiting_on_us) return "tone-watch";
  return "tone-neutral";
}

function PriorityQueueModal({
  threads,
  currentIndex,
  onClose,
  onPrevious,
  onNext,
}: {
  threads: EmailThread[];
  currentIndex: number;
  onClose: () => void;
  onPrevious: () => void;
  onNext: () => void;
}) {
  const activeThread = threads[currentIndex] ?? null;
  const seenMutation = useSeenMutation(activeThread?.thread_id ?? "");
  const pinMutation = usePinMutation(activeThread?.thread_id ?? "");
  const toneClass = activeThread ? priorityWorkflowTone(activeThread) : "tone-neutral";

  return (
    <div className="pq-overlay" onClick={onClose}>
      <div className="pq-modal" onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div className="pq-header">
          <span className="pq-header__eyebrow">
            Priority Queue{threads.length > 0 ? ` · ${currentIndex + 1} of ${threads.length}` : ""}
          </span>
          <div className="pq-header__actions">
            {activeThread && (
              <>
                <DraftComposer thread={activeThread} recommended={Boolean(activeThread.analysis?.should_draft_reply)} iconOnly />
                <button
                  className={`td-action-btn ${activeThread.seen_state?.seen ? "td-action-btn--active" : ""}`}
                  onClick={() => seenMutation.mutate(!(activeThread.seen_state?.seen ?? false))}
                  title={activeThread.seen_state?.seen ? "Undo done" : "Mark as done"}
                >
                  <FontAwesomeIcon icon={activeThread.seen_state?.seen ? faSquareCheck : faSquare} />
                </button>
                <button
                  className={`td-action-btn ${activeThread.seen_state?.pinned ? "td-action-btn--pinned" : ""}`}
                  onClick={() => pinMutation.mutate(!(activeThread.seen_state?.pinned ?? false))}
                  title={activeThread.seen_state?.pinned ? "Unpin" : "Pin"}
                >
                  <FontAwesomeIcon icon={faThumbtack} />
                </button>
              </>
            )}
            <button className="td-action-btn" onClick={onClose} aria-label="Close">
              <FontAwesomeIcon icon={faXmark} />
            </button>
          </div>
        </div>

        <div className="pq-divider" />

        {/* Scrollable content */}
        <div className="pq-content">
          {activeThread ? (
            <>
              <div className="pq-meta">
                <span className={`pill ${toneClass}`}>{priorityWorkflowLabel(activeThread)}</span>
                {activeThread.analysis?.urgency && activeThread.analysis.urgency !== "unknown" && (
                  <span className="pill tone-outline">{activeThread.analysis.urgency}</span>
                )}
              </div>
              <h2 className="pq-subject">{activeThread.subject || "Untitled thread"}</h2>

              <div className="pq-block pq-block--accent">
                <p className="pq-label">Next action</p>
                <p className="pq-value pq-value--strong">
                  {activeThread.analysis?.next_action ?? "Open the thread and decide the next step."}
                </p>
              </div>

              {activeThread.analysis?.summary && (
                <div className="pq-block">
                  <p className="pq-label">Summary</p>
                  <p className="pq-value">{activeThread.analysis.summary}</p>
                </div>
              )}
            </>
          ) : (
            <div className="pq-empty">
              <p className="pq-value">You've reached the end of the priority queue.</p>
            </div>
          )}
        </div>

        <div className="pq-divider" />

        {/* Footer */}
        <div className="pq-footer">
          <div className="pq-nav">
            <button className="pq-nav__btn" type="button" onClick={onPrevious} disabled={currentIndex === 0} title="Previous">
              <FontAwesomeIcon icon={faArrowLeft} />
            </button>
            <button className="pq-nav__btn" type="button" onClick={onNext} title="Next">
              <FontAwesomeIcon icon={faArrowRight} />
            </button>
          </div>
          {activeThread && (
            <Link to={`/threads/${activeThread.thread_id}`} className="pq-open-link" onClick={onClose}>
              Open thread
              <FontAwesomeIcon icon={faArrowUpRightFromSquare} />
            </Link>
          )}
        </div>

      </div>
    </div>
  );
}

function fakeProgressTarget(status: SyncRunStatus | null): number {
  return status ? Math.max(1, status.progress_percent) : 0;
}

function shouldUseTimeBasedSmoothing(stage: string): boolean {
  return stage === "queued" || stage === "fetching" || stage === "summarizing";
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
};

type CollapsibleThreadSectionProps = {
  section: InboxSection;
  defaultOpen: boolean;
};

function CollapsibleThreadSection({
  section,
  defaultOpen,
}: CollapsibleThreadSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = `thread-section-${section.id}`;

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
                <ThreadCard key={thread.thread_id} thread={thread} />
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
          ? "We are checking Gmail now. If nothing new is found, this view will stay empty without a loading skeleton."
          : "Your local queue is currently empty. Refresh Gmail when you want to pull the latest messages into the app."}
      </p>
    </section>
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
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [isSyncSettling, setIsSyncSettling] = useState(false);
  const [displayedProgress, setDisplayedProgress] = useState(0);
  const [animatedPercent, setAnimatedPercent] = useState(0);
  const animFrameRef = useRef<number | null>(null);
  const animTargetRef = useRef(0);

  useEffect(() => {
    animTargetRef.current = displayedProgress;
    if (animFrameRef.current !== null) cancelAnimationFrame(animFrameRef.current);
    const tick = () => {
      setAnimatedPercent((cur) => {
        const target = animTargetRef.current;
        if (cur >= target) return target;
        const step = Math.max(1, Math.ceil((target - cur) / 8));
        const next = Math.min(cur + step, target);
        animFrameRef.current = requestAnimationFrame(tick);
        return next;
      });
    };
    animFrameRef.current = requestAnimationFrame(tick);
    return () => { if (animFrameRef.current !== null) cancelAnimationFrame(animFrameRef.current); };
  }, [displayedProgress]);

  const [stageStartedAt, setStageStartedAt] = useState<number | null>(null);
  const [activeStageKey, setActiveStageKey] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [priorityFilter, setPriorityFilter] =
    useState<PriorityFilterValue>("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [syncLookbackDays, setSyncLookbackDays] = useState(7);
  const [isPriorityModalOpen, setIsPriorityModalOpen] = useState(false);
  const [priorityModalIndex, setPriorityModalIndex] = useState(0);
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

    if (syncStatus.run_id === handledCompletionRunIdRef.current) {
      return;
    }

    handledCompletionRunIdRef.current = syncStatus.run_id;
    setIsSyncSettling(true);
    setDisplayedProgress((current) =>
      syncStatus.status === "completed"
        ? Math.max(current, 100)
        : Math.max(current, syncStatus.progress_percent || 100),
    );

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
      setStageStartedAt(null);
      setActiveStageKey(null);
      setActiveRunId(null);
      setDisplayedProgress(0);
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
        normalizedCategory(thread) === categoryFilter),
    );
  }, [categoryFilter, deferredSearch, priorityFilter, queueThreads]);

  const sections = useMemo(
    () => sectionedThreads(filteredThreads),
    [filteredThreads],
  );
  const priorityThreads = useMemo(
    () => topPriorityThreads(filteredThreads),
    [filteredThreads],
  );
  useEffect(() => {
    if (!priorityThreads.length) {
      setPriorityModalIndex(0);
      return;
    }

    setPriorityModalIndex((current) => Math.min(current, priorityThreads.length));
  }, [priorityThreads.length]);
  const hasActiveFilters =
    deferredSearch.trim().length > 0 ||
    priorityFilter !== "all" ||
    categoryFilter !== "all";

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

  const openPriorityModal = () => {
    setPriorityModalIndex(0);
    setIsPriorityModalOpen(true);
  };

  const advancePriorityModal = () => {
    setPriorityModalIndex((current) => current + 1);
  };

  const retreatPriorityModal = () => {
    setPriorityModalIndex((current) => Math.max(0, current - 1));
  };

  return (
    <section className="page page--inbox stack stack--page">
      <div className="inbox-header">
        <div className="inbox-header__left">
          <p className="inbox-header__eyebrow">
            Daily Queue · {new Date().toLocaleDateString("en-CA", { weekday: "short", month: "short", day: "numeric" })}
          </p>
          <h1 className="inbox-header__title">Inbox</h1>
          {queueThreads.length > 0 && (
            <div className="inbox-header__stats">
              {actNowCount > 0 && <span className="inbox-header__stat inbox-header__stat--urgent">{actNowCount} act now</span>}
              {waitingCount > 0 && <span className="inbox-header__stat inbox-header__stat--watch">{waitingCount} waiting</span>}
              {pinnedCount > 0 && <span className="inbox-header__stat inbox-header__stat--pinned">{pinnedCount} pinned</span>}
              <span className="inbox-header__stat">{queueThreads.length} total</span>
            </div>
          )}
          {isLoading && !data ? (
            <div className="inbox-header__summary-skeleton">
              <SkeletonLine width="72%" />
              <SkeletonLine width="52%" />
            </div>
          ) : data?.summary.executive_summary?.trim() ? (
            <p className="inbox-header__summary">{data.summary.executive_summary}</p>
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
                  : "Refresh Gmail"}
          </button>
          <button
            type="button"
            className="inbox-header__btn inbox-header__btn--ghost"
            onClick={openPriorityModal}
            disabled={!priorityThreads.length}
          >
            {priorityThreads.length ? `Priority queue (${priorityThreads.length})` : "Priority queue"}
          </button>
        </div>
      </div>
      {showSyncProgress && syncStatus ? (
        <div className="sync-bar">
          <div className="sync-bar__top">
            <span className="sync-bar__label">{syncStatus.status_message || stageLabel(syncStatus.stage)}</span>
            <span className="sync-bar__percent">{animatedPercent}%</span>
          </div>
          <div className="sync-bar__track" aria-hidden="true">
            <span className="sync-bar__fill" style={{ width: `${displayedProgress}%` }} />
          </div>
          <div className="sync-bar__stats">
            <span>{syncStatus.fetched_message_count} messages</span>
            <span>{syncStatus.thread_count} threads</span>
            <span>{syncStatus.ai_thread_count} AI-reviewed</span>
          </div>
        </div>
      ) : null}

      <div className="inbox-header__divider" />

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
            <button
              className={`inbox-toolbar__clear${hasActiveFilters ? "" : " inbox-toolbar__clear--inactive"}`}
              type="button"
              tabIndex={hasActiveFilters ? 0 : -1}
              onClick={() => {
                if (!hasActiveFilters) return;
                setSearch("");
                setPriorityFilter("all");
                setCategoryFilter("all");
              }}
            >
              Clear
            </button>
          </div>
        </div>
      <div className="inbox-header__divider" />


      {showInitialSkeleton ? <QueueSkeleton /> : null}
      {showRefreshSkeleton ? <QueueSkeleton refreshing /> : null}
      {showEmptyState ? <EmptyInboxState syncing={isSyncing} /> : null}

      {isPriorityModalOpen ? (
        <PriorityQueueModal
          threads={priorityThreads}
          currentIndex={priorityModalIndex}
          onClose={() => setIsPriorityModalOpen(false)}
          onPrevious={retreatPriorityModal}
          onNext={advancePriorityModal}
        />
      ) : null}

      {error instanceof Error ? <p>{error.message}</p> : null}
      {syncMutation.error instanceof Error ? <p>{syncMutation.error.message}</p> : null}
      {syncRunQuery.error instanceof Error ? <p>{syncRunQuery.error.message}</p> : null}

      {shouldRenderInboxContent
        ? sections.map((section) => (
          <CollapsibleThreadSection
            key={section.id}
            section={section}
            defaultOpen={SECTION_DEFAULT_OPEN[section.id] ?? true}
          />
        ))
        : null}
    </section>
  );
}
