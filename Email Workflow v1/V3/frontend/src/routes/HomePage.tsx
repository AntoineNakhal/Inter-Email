import {
  faArrowLeft,
  faArrowRight,
  faArrowUpRightFromSquare,
  faSquareCheck,
  faThumbtack,
} from "@fortawesome/free-solid-svg-icons";
import { faSquare } from "@fortawesome/free-regular-svg-icons";

const SPOTLIGHT_CATEGORIES = [
  { key: "Urgent / Executive", label: "Urgent / Executive", accent: "var(--alert)" },
  { key: "Customer / Partner", label: "Customer / Partner", accent: "#185FA5" },
  { key: "Finance / Admin",    label: "Finance / Admin",    accent: "#854F0B" },
  { key: "Events / Logistics", label: "Events / Logistics", accent: "#3B6D11" },
  { key: "FYI / Low Priority", label: "FYI / Low",          accent: "var(--muted)" },
] as const;

const URGENCY_COLOR: Record<string, string> = {
  high:    "var(--alert)",
  medium:  "var(--warn)",
  low:     "var(--accent)",
  unknown: "var(--muted)",
};

function spotlightThreadsForCategory(threads: EmailThread[], categoryKey: string): EmailThread[] {
  return threads
    .filter((t) => !t.seen_state?.seen && !t.resolved_or_closed && t.analysis?.category === categoryKey)
    .sort((a, b) => {
      const order = ["high", "medium", "low", "unknown"];
      return order.indexOf(a.analysis?.urgency ?? "unknown") - order.indexOf(b.analysis?.urgency ?? "unknown");
    })
    .slice(0, 3);
}

function CategorySpotlightPanel({ threads }: { threads: EmailThread[] }) {
  return (
    <div className="home-panel home-panel--spotlight">
      <div className="home-panel__head">
        <div>
          <p className="home-panel__eyebrow">Backlog</p>
          <h3 className="home-panel__title">Top priorities by category</h3>
        </div>
        <Link to="/inbox" className="home-panel__link" style={{ fontSize: "0.78rem" }}>
          Full inbox <FontAwesomeIcon icon={faArrowRight} />
        </Link>
      </div>
      <div className="db-spotlight-list">
        {SPOTLIGHT_CATEGORIES.map(({ key, label, accent }) => {
          const top = spotlightThreadsForCategory(threads, key);
          return (
            <div key={key} className="db-srow">
              <div className="db-srow__cat">
                <span className="db-srow__dot" style={{ background: accent }} />
                <span className="db-srow__label">{label}</span>
              </div>
              <div className="db-srow__chips">
                {top.length > 0 ? top.map((t) => (
                  <Link key={t.thread_id} to={`/threads/${t.thread_id}`} className="db-chip">
                    <span className="db-chip__top">
                      <span className="db-chip__dot" style={{ background: URGENCY_COLOR[t.analysis?.urgency ?? "unknown"] }} />
                      <span className="db-chip__subject">{t.subject || "Untitled"}</span>
                    </span>
                    <span className="db-chip__action">
                      {t.analysis?.needs_next_action ? t.analysis.next_action : "No action needed right now."}
                    </span>
                  </Link>
                )) : (
                  <span className="db-srow__empty">All clear</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { DraftComposer } from "../features/drafts/DraftComposer";
import { usePinMutation, useQueueDashboard, useSeenMutation } from "../hooks/useApi";
import { formatDate } from "../lib/format";
import type { EmailThread } from "../types/api";

function isSeen(thread: EmailThread): boolean {
  return Boolean(thread.seen_state?.seen);
}

function isPinned(thread: EmailThread): boolean {
  return Boolean(thread.seen_state?.pinned);
}

function isOpenWork(thread: EmailThread): boolean {
  return !isSeen(thread) && !thread.resolved_or_closed;
}

function isWaitingOnOthers(thread: EmailThread): boolean {
  return (
    isOpenWork(thread) &&
    Boolean(thread.latest_message_from_me) &&
    !thread.waiting_on_us &&
    !thread.analysis?.needs_action_today
  );
}

function focusScore(thread: EmailThread): number {
  let score = 0;
  if (thread.analysis?.needs_action_today) score += 120;
  if (isPinned(thread)) score += 90;
  if (thread.analysis?.urgency === "high") score += 70;
  if (thread.waiting_on_us) score += 45;
  if (thread.analysis?.should_draft_reply) score += 20;
  if (thread.is_new) score += 12;
  score -= Math.min(thread.message_count, 12);
  return score;
}

function quickWinScore(thread: EmailThread): number {
  let score = focusScore(thread);
  if (thread.analysis?.should_draft_reply) score += 30;
  if (thread.message_count <= 2) score += 18;
  if ((thread.analysis?.next_action ?? "").length <= 120) score += 8;
  return score;
}

function workflowLabel(thread: EmailThread): string {
  if (thread.analysis?.needs_action_today) return "Act today";
  if (thread.waiting_on_us) return "Waiting on me";
  if (isPinned(thread)) return "Pinned";
  return "Monitor";
}

function workflowTone(thread: EmailThread): string {
  if (thread.analysis?.needs_action_today) return "tone-urgent";
  if (thread.waiting_on_us) return "tone-watch";
  return "tone-neutral";
}

function focusCandidates(threads: EmailThread[]): EmailThread[] {
  return [...threads]
    .filter(
      (thread) =>
        isOpenWork(thread) &&
        Boolean(thread.analysis?.needs_next_action) &&
        (
          Boolean(thread.analysis?.needs_action_today) ||
          Boolean(thread.waiting_on_us) ||
          thread.analysis?.urgency === "high" ||
          isPinned(thread)
        ),
    )
    .sort((left, right) => focusScore(right) - focusScore(left));
}

function quickWins(threads: EmailThread[]): EmailThread[] {
  return [...threads]
    .filter(
      (thread) =>
        isOpenWork(thread) &&
        Boolean(thread.analysis?.needs_next_action) &&
        (
          Boolean(thread.analysis?.should_draft_reply) ||
          thread.message_count <= 2 ||
          Boolean(thread.analysis?.needs_action_today)
        ),
    )
    .sort((left, right) => quickWinScore(right) - quickWinScore(left))
    .slice(0, 5);
}

function waitingOnOthers(threads: EmailThread[]): EmailThread[] {
  return [...threads]
    .filter(isWaitingOnOthers)
    .sort((left, right) => {
      const leftTime = left.latest_message_date ? new Date(left.latest_message_date).getTime() : 0;
      const rightTime = right.latest_message_date ? new Date(right.latest_message_date).getTime() : 0;
      return rightTime - leftTime;
    })
    .slice(0, 5);
}

function pinnedThreads(threads: EmailThread[]): EmailThread[] {
  return [...threads]
    .filter((thread) => isOpenWork(thread) && isPinned(thread))
    .sort((left, right) => focusScore(right) - focusScore(left))
    .slice(0, 4);
}

function CommandCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: number;
  sub: string;
  accent?: string;
}) {
  return (
    <div className="db-cmd">
      <p className="db-cmd__label">{label}</p>
      <p className="db-cmd__value" style={{ color: accent }}>{value}</p>
      <p className="db-cmd__sub">{sub}</p>
    </div>
  );
}

function ActionRow({
  thread,
  showDraft = false,
}: {
  thread: EmailThread;
  showDraft?: boolean;
}) {
  const seenMutation = useSeenMutation(thread.thread_id);
  const pinMutation = usePinMutation(thread.thread_id);

  return (
    <div className="home-row">
      <Link to={`/threads/${thread.thread_id}`} className="home-row__link">
        <div className="home-row__top">
          <span className={`pill ${workflowTone(thread)}`}>{workflowLabel(thread)}</span>
          {thread.analysis?.urgency && thread.analysis.urgency !== "unknown" ? (
            <span className="pill tone-outline">{thread.analysis.urgency}</span>
          ) : null}
        </div>
        <span className="home-row__subject">{thread.subject || "Untitled thread"}</span>
        <span className="home-row__action">
          {thread.analysis?.needs_next_action
            ? thread.analysis.next_action
            : "No action needed right now."}
        </span>
      </Link>
      <div className="home-row__actions">
        {showDraft ? (
          <DraftComposer
            thread={thread}
            recommended={Boolean(
              thread.analysis?.needs_next_action && thread.analysis?.should_draft_reply,
            )}
            iconOnly
          />
        ) : null}
        <button
          className={`td-action-btn ${thread.seen_state?.seen ? "td-action-btn--active" : ""}`}
          type="button"
          onClick={() => seenMutation.mutate(!(thread.seen_state?.seen ?? false))}
          title={thread.seen_state?.seen ? "Undo done" : "Mark as done"}
        >
          <FontAwesomeIcon icon={faSquareCheck} />
        </button>
        <button
          className={`td-action-btn ${thread.seen_state?.pinned ? "td-action-btn--pinned" : ""}`}
          type="button"
          onClick={() => pinMutation.mutate(!(thread.seen_state?.pinned ?? false))}
          title={thread.seen_state?.pinned ? "Unpin" : "Pin"}
        >
          <FontAwesomeIcon icon={faThumbtack} />
        </button>
      </div>
    </div>
  );
}

export function HomePage() {
  const { data, isLoading, error } = useQueueDashboard();
  const threads = data?.threads ?? [];
  const [focusIndex, setFocusIndex] = useState(0);

  const actionableThreads = useMemo(() => focusCandidates(threads), [threads]);
  const hasMultipleFocusThreads = actionableThreads.length > 1;
  const activeFocusThreadId = actionableThreads[focusIndex]?.thread_id ?? null;
  const quickWinThreads = useMemo(
    () =>
      quickWins(threads).filter((thread) => thread.thread_id !== activeFocusThreadId),
    [activeFocusThreadId, threads],
  );
  const waitingThreads = useMemo(() => waitingOnOthers(threads), [threads]);
  const pinnedOpenThreads = useMemo(() => pinnedThreads(threads), [threads]);

  useEffect(() => {
    if (actionableThreads.length === 0) {
      setFocusIndex(0);
      return;
    }
    setFocusIndex((current) => Math.min(current, actionableThreads.length - 1));
  }, [actionableThreads.length]);

  const activeFocus = actionableThreads[focusIndex] ?? null;
  const openThreads = threads.filter(isOpenWork);
  const actTodayCount = openThreads.filter((thread) => thread.analysis?.needs_action_today).length;
  const quickWinsCount = quickWinThreads.length;
  const waitingOnOthersCount = waitingThreads.length;
  const pinnedCount = openThreads.filter(isPinned).length;

  const focusSeenMutation = useSeenMutation(activeFocus?.thread_id ?? "");
  const focusPinMutation = usePinMutation(activeFocus?.thread_id ?? "");

  const cycleFocus = (direction: -1 | 1) => {
    setFocusIndex((current) => {
      if (!hasMultipleFocusThreads) {
        return 0;
      }
      return (current + direction + actionableThreads.length) % actionableThreads.length;
    });
  };

  return (
    <section className="page home-page">
      <div className="sp-header home-header">
        <div>
          <p className="sp-header__eyebrow">Today</p>
          <h1 className="sp-header__title">Home</h1>
          <p className="sp-header__sub">
            {data?.summary.executive_summary?.trim()
              ? data.summary.executive_summary
              : "Start with what needs action now, clear the quick wins, then move to the backlog."}
          </p>
        </div>
        <div className="home-header__actions">
          <Link to="/inbox" className="sp-connect-btn">Open inbox</Link>
          <Link to="/dashboard" className="sp-connect-btn">Dashboard</Link>
        </div>
      </div>

      <div className="sp-divider" />

      {isLoading ? <p className="rp-loading">Loading focus view...</p> : null}
      {error instanceof Error ? <p className="rp-error">{error.message}</p> : null}

      {!isLoading && !error ? (
        <>
          <div className="db-cmd-strip">
            <CommandCard label="Act today" value={actTodayCount} sub="must move today" accent="var(--alert)" />
            <CommandCard label="Quick wins" value={quickWinsCount} sub="clear fast" accent="var(--accent)" />
            <CommandCard label="Waiting on others" value={waitingOnOthersCount} sub="monitor only" accent="var(--warn)" />
            <CommandCard label="Pinned" value={pinnedCount} sub="keep in sight" accent="#534ab7" />
          </div>

          <div className="sp-divider" />

          <div className="home-grid">
            <div className="home-main">
              <div className="home-panel home-focus">
                <div className="home-focus__header">
                  <div>
                    <p className="home-panel__eyebrow">
                      Today focus{actionableThreads.length ? ` - ${focusIndex + 1} of ${actionableThreads.length}` : ""}
                    </p>
                    <h2 className="home-focus__title">
                      {activeFocus?.subject || "No urgent thread to process"}
                    </h2>
                    {activeFocus ? (
                      <p className="home-focus__meta">
                        {activeFocus.participants.join(", ") || "No participants"} - {formatDate(activeFocus.latest_message_date)}
                      </p>
                    ) : (
                      <p className="home-focus__meta">
                        Everything urgent is clear. Use Inbox for backlog review.
                      </p>
                    )}
                  </div>
                  {activeFocus ? (
                    <Link to={`/threads/${activeFocus.thread_id}`} className="home-focus__open">
                      Open thread
                      <FontAwesomeIcon icon={faArrowUpRightFromSquare} />
                    </Link>
                  ) : null}
                </div>

                {activeFocus ? (
                  <>
                    <div className="home-focus__pills">
                      <span className={`pill ${workflowTone(activeFocus)}`}>{workflowLabel(activeFocus)}</span>
                      {activeFocus.analysis?.urgency && activeFocus.analysis.urgency !== "unknown" ? (
                        <span className="pill tone-outline">{activeFocus.analysis.urgency}</span>
                      ) : null}
                      <span className="pill tone-outline">{activeFocus.analysis?.category ?? "Needs review"}</span>
                    </div>

                    <div className="home-focus__block">
                      <p className="home-focus__label">Why this matters</p>
                      <p className="home-focus__value">
                        {activeFocus.analysis?.summary || "This thread needs a manual review."}
                      </p>
                    </div>

                    <div className="home-focus__block home-focus__block--accent">
                      <p className="home-focus__label">Next action</p>
                      <p className="home-focus__value home-focus__value--strong">
                        {activeFocus.analysis?.needs_next_action
                          ? activeFocus.analysis.next_action
                          : "No action needed right now."}
                      </p>
                    </div>

                    <div className="home-focus__actions">
                      <DraftComposer
                        thread={activeFocus}
                        recommended={Boolean(
                          activeFocus.analysis?.needs_next_action &&
                            activeFocus.analysis?.should_draft_reply,
                        )}
                        iconOnly
                      />
                      <button
                        className={`td-action-btn${activeFocus.seen_state?.seen ? " td-action-btn--active" : ""}`}
                        type="button"
                        onClick={() => focusSeenMutation.mutate(!(activeFocus.seen_state?.seen ?? false))}
                        title={activeFocus.seen_state?.seen ? "Undo done" : "Mark done"}
                      >
                        <FontAwesomeIcon icon={activeFocus.seen_state?.seen ? faSquareCheck : faSquare} />
                      </button>
                      <button
                        className={`td-action-btn${activeFocus.seen_state?.pinned ? " td-action-btn--pinned" : ""}`}
                        type="button"
                        onClick={() => focusPinMutation.mutate(!(activeFocus.seen_state?.pinned ?? false))}
                        title={activeFocus.seen_state?.pinned ? "Unpin" : "Pin"}
                      >
                        <FontAwesomeIcon icon={faThumbtack} />
                      </button>
                      {hasMultipleFocusThreads ? (
                        <div className="home-focus__nav" aria-label="Today focus navigation">
                          <button
                            className="home-focus__open"
                            style={{ background: "none", border: "none", cursor: "pointer" }}
                            type="button"
                            onClick={() => cycleFocus(-1)}
                          >
                            <FontAwesomeIcon icon={faArrowLeft} />
                            Prev
                          </button>
                          <button
                            className="home-focus__open"
                            style={{ background: "none", border: "none", cursor: "pointer" }}
                            type="button"
                            onClick={() => cycleFocus(1)}
                          >
                            Next
                            <FontAwesomeIcon icon={faArrowRight} />
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </>
                ) : (
                  <div className="home-empty">
                    <p className="home-empty__text">
                      No act-today, pinned, or high-priority thread is currently blocking you.
                    </p>
                    <div className="home-empty__actions">
                      <Link to="/inbox" className="button">Open inbox backlog</Link>
                    </div>
                  </div>
                )}
              </div>

              <div className="home-panel">
                <div className="home-panel__head">
                  <div>
                    <p className="home-panel__eyebrow">Quick wins</p>
                    <h3 className="home-panel__title">Clear these first</h3>
                  </div>
                  <span className="home-panel__count">{quickWinThreads.length}</span>
                </div>
                {quickWinThreads.length ? (
                  <div className="home-list">
                    {quickWinThreads.map((thread) => (
                      <ActionRow
                        key={thread.thread_id}
                        thread={thread}
                        showDraft={Boolean(
                          thread.analysis?.needs_next_action &&
                            thread.analysis?.should_draft_reply,
                        )}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="db-chart__empty">No obvious quick wins right now.</p>
                )}
              </div>
            </div>

            <div className="home-side">
              <div className="home-panel">
                <div className="home-panel__head">
                  <div>
                    <p className="home-panel__eyebrow">Waiting on others</p>
                    <h3 className="home-panel__title">No action needed now</h3>
                  </div>
                  <span className="home-panel__count">{waitingThreads.length}</span>
                </div>
                {waitingThreads.length ? (
                  <div className="home-list">
                    {waitingThreads.map((thread) => (
                      <ActionRow key={thread.thread_id} thread={thread} />
                    ))}
                  </div>
                ) : (
                  <p className="db-chart__empty">Nothing is currently waiting on external follow-up.</p>
                )}
              </div>

              <div className="home-panel">
                <div className="home-panel__head">
                  <div>
                    <p className="home-panel__eyebrow">Pinned</p>
                    <h3 className="home-panel__title">Keep these visible</h3>
                  </div>
                  <span className="home-panel__count">{pinnedOpenThreads.length}</span>
                </div>
                {pinnedOpenThreads.length ? (
                  <div className="home-list">
                    {pinnedOpenThreads.map((thread) => (
                      <ActionRow key={thread.thread_id} thread={thread} showDraft={false} />
                    ))}
                  </div>
                ) : (
                  <p className="db-chart__empty">No pinned thread in the active queue.</p>
                )}
              </div>

              <CategorySpotlightPanel threads={threads} />
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}
