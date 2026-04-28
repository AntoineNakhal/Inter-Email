import { Link } from "react-router-dom";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faThumbtack } from "@fortawesome/free-solid-svg-icons";

import type { EmailThread } from "../types/api";
import { usePinMutation } from "../hooks/useApi";

const isDone = (thread: EmailThread) => Boolean(thread.seen_state?.seen);

function statusLabel(thread: EmailThread): string {
  if (isDone(thread)) return "Done";
  if (thread.analysis?.needs_action_today) return "Act today";
  if (thread.waiting_on_us) return "Waiting";
  if (thread.resolved_or_closed) return "Closed";
  return "Monitor";
}

function statusTone(thread: EmailThread): string {
  if (isDone(thread)) return "neutral";
  if (thread.analysis?.needs_action_today) return "urgent";
  if (thread.waiting_on_us) return "watch";
  return "neutral";
}

function urgencyTone(urgency: string | undefined): string {
  if (urgency === "high") return "tone-urgent";
  if (urgency === "medium") return "tone-watch";
  return "tone-neutral";
}

export function ThreadCard({ thread }: { thread: EmailThread }) {
  const pinMutation = usePinMutation(thread.thread_id);
  const tone = statusTone(thread);
  const label = statusLabel(thread);
  const nextAction = thread.analysis?.next_action || "Open to review.";
  const urgency = thread.analysis?.urgency;

  return (
    <div className="thread-row">
      <Link
        to={`/threads/${thread.thread_id}`}
        className="thread-row__link"
      >
        <div className="thread-row__top">
          <span className={`pill tone-${tone}`}>{label}</span>
          <span className="thread-row__subject">{thread.subject || "Untitled thread"}</span>
          {thread.analysis?.needs_human_review ? (
            <span className="pill tone-watch" style={{ fontSize: "0.7rem" }}>Review</span>
          ) : null}
          {urgency && urgency !== "unknown" ? (
            <span className={`pill ${urgencyTone(urgency)}`} style={{ marginLeft: "auto", flexShrink: 0 }}>
              {urgency}
            </span>
          ) : null}
        </div>
        <p className="thread-row__action">
          <span className="thread-row__action-arrow">→</span>
          {nextAction}
        </p>
      </Link>

      <button
        className={`thread-card__pin-btn ${thread.seen_state?.pinned ? "thread-card__pin-btn--active" : ""}`}
        title={thread.seen_state?.pinned ? "Unpin" : "Pin"}
        aria-label={thread.seen_state?.pinned ? "Unpin thread" : "Pin thread"}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          pinMutation.mutate(!(thread.seen_state?.pinned ?? false));
        }}
      >
        <FontAwesomeIcon icon={faThumbtack} className="thread-card__pin-icon" />
      </button>
    </div>
  );
}
