import { Link } from "react-router-dom";

import type { EmailThread } from "../types/api";
import { formatDate } from "../lib/format";

type ThreadCardProps = {
  thread: EmailThread;
};

function workflowLabel(thread: EmailThread): string {
  if (thread.analysis?.needs_action_today) {
    return "Act today";
  }
  if (thread.waiting_on_us) {
    return "Waiting on us";
  }
  if (thread.resolved_or_closed) {
    return "Closed";
  }
  return "Monitor";
}

function workflowTone(thread: EmailThread): string {
  if (thread.analysis?.needs_action_today) {
    return "urgent";
  }
  if (thread.waiting_on_us) {
    return "watch";
  }
  return "neutral";
}

function summaryText(thread: EmailThread): string {
  return (
    thread.analysis?.summary ||
    "Run a refresh to generate a summary for this thread."
  );
}

function nextActionText(thread: EmailThread): string {
  return (
    thread.analysis?.next_action ||
    "Open the thread to review the latest message and decide the next step."
  );
}

export function ThreadCard({ thread }: ThreadCardProps) {
  const toneClass = workflowTone(thread);
  const statusLabel = workflowLabel(thread);
  const badgeToneClass = `tone-${toneClass}`;

  return (
    <article className={`thread-card thread-card--stacked thread-card--${toneClass}`}>
      <div className="thread-card__topline">
        <div className="thread-card__badges">
          <span className={`pill ${badgeToneClass}`}>{statusLabel}</span>
          <span className="pill tone-outline">
            {thread.analysis?.category ?? "Needs review"}
          </span>
          {thread.seen_state?.seen ? (
            <span className="pill tone-outline">Seen</span>
          ) : (
            <span className="pill tone-outline">New</span>
          )}
        </div>
        <span className={`pill ${badgeToneClass}`}>
          {thread.analysis?.urgency ?? "unknown"}
        </span>
      </div>

      <div className="thread-card__header thread-card__header--stacked">
        <div className="thread-card__title-block">
          <h3>{thread.subject || "Untitled thread"}</h3>
          <p className="thread-card__meta">
            {thread.participants.slice(0, 4).join(", ") || "No participants"} |{" "}
            {thread.message_count} messages | {formatDate(thread.latest_message_date)}
          </p>
        </div>
      </div>

      <div className="thread-card__content">
        <section className="thread-card__section">
          <p className="thread-card__label">Summary</p>
          <p className="thread-card__summary thread-card__clamp">
            {summaryText(thread)}
          </p>
        </section>

        <section className="thread-card__section thread-card__section--action">
          <p className="thread-card__label">Next action</p>
          <p className="thread-card__action thread-card__clamp">
            {nextActionText(thread)}
          </p>
        </section>
      </div>

      <div className="thread-card__footer">
        <div className="thread-card__footer-meta">
          <span className="thread-card__status-line">
            {thread.analysis?.current_status || "No current status yet."}
          </span>
        </div>
        <Link className="button button--ghost" to={`/threads/${thread.thread_id}`}>
          Open thread
        </Link>
      </div>
    </article>
  );
}
