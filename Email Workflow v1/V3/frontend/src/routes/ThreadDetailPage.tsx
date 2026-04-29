import { useState, useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faEnvelope, faSquare } from "@fortawesome/free-regular-svg-icons";
import { faBolt, faArrowLeft, faCopy, faSquareCheck, faThumbtack, faWandMagicSparkles } from "@fortawesome/free-solid-svg-icons";

import { DraftComposer } from "../features/drafts/DraftComposer";
import { useAnalyzeMutation, usePinMutation, useSeenMutation, useThread } from "../hooks/useApi";
import { formatDate } from "../lib/format";
import { formatInlineText, formatMessageExcerpt } from "../lib/messageFormat";

function workflowLabel(thread: {
  analysis: { needs_action_today: boolean } | null;
  waiting_on_us: boolean;
  resolved_or_closed: boolean;
}) {
  if (thread.analysis?.needs_action_today) return "Act today";
  if (thread.waiting_on_us) return "Waiting on us";
  if (thread.resolved_or_closed) return "Closed";
  return "Monitor";
}

function workflowTone(thread: {
  analysis: { needs_action_today: boolean } | null;
  waiting_on_us: boolean;
}) {
  if (thread.analysis?.needs_action_today) return "tone-urgent";
  if (thread.waiting_on_us) return "tone-watch";
  return "tone-neutral";
}

function gmailThreadUrl(threadId: string) {
  return `https://mail.google.com/mail/u/0/#all/${encodeURIComponent(threadId)}`;
}

function MessageTimelineItem({
  message,
  index,
}: {
  message: {
    message_id: string;
    sender: string;
    recipients: string[];
    subject: string;
    sent_at: string | null;
    snippet: string;
    cleaned_body: string;
  };
  index: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const excerpt = formatMessageExcerpt(message.cleaned_body, message.snippet);
  const shouldClamp = excerpt.length > 360;

  return (
    <article className="td-message">
      <div className="td-message__header">
        <div className="td-message__sender">
          <strong>{formatInlineText(message.sender) || "Unknown sender"}</strong>
          <span className="td-message__time">{formatDate(message.sent_at)}</span>
        </div>
        <span className="td-message__index">#{index + 1}</span>
      </div>

      {message.recipients.length ? (
        <p className="td-message__recipients">
          To: {message.recipients.map((r) => formatInlineText(r)).join(", ")}
        </p>
      ) : null}

      {excerpt ? (
        <div
          className={`td-message__body${shouldClamp ? " td-message__body--clickable" : ""}`}
          onClick={() => { if (shouldClamp) setExpanded((v) => !v); }}
          role={shouldClamp ? "button" : undefined}
          tabIndex={shouldClamp ? 0 : undefined}
          onKeyDown={(e) => { if (shouldClamp && (e.key === "Enter" || e.key === " ")) setExpanded((v) => !v); }}
        >
          <p className={`td-message__excerpt${shouldClamp && !expanded ? " td-message__excerpt--clamped" : ""}`}>
            {excerpt}
          </p>
          {shouldClamp ? (
            <span className="td-message__toggle">
              {expanded ? "Show less" : "Show more"}
            </span>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function DraftBlock({ draft }: { draft: { subject: string; body: string } }) {
  const [copied, setCopied] = useState(false);

  function copy() {
    const text = draft.body;
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }

  return (
    <div className="td-analysis__draft">
      <p className="td-analysis__label">Generated draft</p>
      <p className="td-analysis__draft-subject">{draft.subject}</p>
      <div className="td-analysis__draft-body-wrap">
        <pre className="td-analysis__draft-body">{draft.body}</pre>
        <button
          className={`td-analysis__draft-copy${copied ? " td-analysis__draft-copy--copied" : ""}`}
          type="button"
          onClick={copy}
          title="Copy draft"
          aria-label="Copy draft to clipboard"
        >
          <FontAwesomeIcon icon={faCopy} />
        </button>
      </div>
    </div>
  );
}

export function ThreadDetailPage() {
  const { threadId } = useParams();
  const { data: thread, isLoading, error } = useThread(threadId);
  const seenMutation = useSeenMutation(threadId ?? "");
  const pinMutation = usePinMutation(threadId ?? "");
  const analyzeMutation = useAnalyzeMutation(threadId ?? "");

  useEffect(() => {
    document.body.classList.add("body--thread-detail");
    return () => document.body.classList.remove("body--thread-detail");
  }, []);

  if (isLoading) return <section className="page td-page"><p className="td-loading">Loading thread…</p></section>;
  if (error instanceof Error) return <section className="page td-page"><p>{error.message}</p></section>;
  if (!thread) return <section className="page td-page"><p>Thread not found.</p></section>;

  const toneClass = workflowTone(thread);

  return (
    <section className="page page--thread td-page">

      {/* Flat header */}
      <div className="td-header">
        <div className="td-header__top">
          <Link to="/" className="td-back">
            <FontAwesomeIcon icon={faArrowLeft} />
            Inbox
          </Link>
          <div className="td-header__actions">
            <button
              className={`td-action-btn${analyzeMutation.isPending ? " td-action-btn--active" : ""}`}
              onClick={() => analyzeMutation.mutate()}
              disabled={analyzeMutation.isPending}
              title={analyzeMutation.isPending ? "Analysing…" : "Analyse with AI"}
              aria-label="Analyse with AI"
            >
              <FontAwesomeIcon icon={faWandMagicSparkles} style={analyzeMutation.isPending ? { animation: "spin 1s linear infinite" } : undefined} />
            </button>
            <DraftComposer thread={thread} recommended={Boolean(thread.analysis?.should_draft_reply)} iconOnly />
            <a
              className="td-action-btn"
              href={gmailThreadUrl(thread.thread_id)}
              target="_blank"
              rel="noreferrer noopener"
              aria-label="Open in Gmail"
              title="Open in Gmail"
            >
              <FontAwesomeIcon icon={faEnvelope} />
            </a>
            <button
              className={`td-action-btn ${thread.seen_state?.seen ? "td-action-btn--active" : ""}`}
              onClick={() => seenMutation.mutate(!(thread.seen_state?.seen ?? false))}
              aria-label={thread.seen_state?.seen ? "Undo done" : "Mark as done"}
              title={thread.seen_state?.seen ? "Undo done" : "Mark as done"}
            >
              <FontAwesomeIcon icon={thread.seen_state?.seen ? faSquareCheck : faSquare} />
            </button>
            <button
              className={`td-action-btn ${thread.seen_state?.pinned ? "td-action-btn--pinned" : ""}`}
              onClick={() => pinMutation.mutate(!(thread.seen_state?.pinned ?? false))}
              aria-label={thread.seen_state?.pinned ? "Unpin" : "Pin"}
              title={thread.seen_state?.pinned ? "Unpin" : "Pin"}
            >
              <FontAwesomeIcon icon={faThumbtack} />
            </button>
          </div>
        </div>

        <h1 className="td-header__subject">
          {formatInlineText(thread.subject) || "Untitled thread"}
        </h1>

        <div className="td-header__meta">
          <span className={`pill ${toneClass}`}>{workflowLabel(thread)}</span>
          {thread.analysis?.urgency && thread.analysis.urgency !== "unknown" && (
            <span className="pill tone-outline">{thread.analysis.urgency}</span>
          )}
          <span className="pill tone-outline">{thread.analysis?.category ?? "Needs review"}</span>
          <span className="pill tone-outline">{thread.message_count} messages</span>
          <span className="pill tone-outline">{formatDate(thread.latest_message_date)}</span>
        </div>

        <p className="td-header__participants">
          {thread.participants.map((p) => formatInlineText(p)).join(", ") || "No participants"}
        </p>
      </div>

      <div className="td-header__divider" />

      {/* Two-column body */}
      <div className="td-body">

        {/* Left: Analysis */}
        <aside className={`td-analysis${analyzeMutation.isPending ? " td-analysis--loading" : ""}`}>

          {analyzeMutation.isPending ? (
            <div className="td-analysis__skeleton">
              <div className="td-skeleton-label" />
              <div className="td-skeleton-line td-skeleton-line--wide" />
              <div className="td-skeleton-line td-skeleton-line--med" />
              <div className="td-skeleton-line td-skeleton-line--narrow" />
              <div className="td-skeleton-divider" />
              <div className="td-skeleton-block" />
              <div className="td-skeleton-block td-skeleton-block--accent" />
              <div className="td-skeleton-divider" />
              <div className="td-skeleton-facts" />
            </div>
          ) : thread.analysis?.summary ? (
            <p className="td-analysis__summary">{thread.analysis.summary}</p>
          ) : (
            <p className="td-analysis__summary td-analysis__summary--empty">No analysis yet. Run a sync or click ✨ to analyse.</p>
          )}

          {!analyzeMutation.isPending && <><div className="td-analysis__divider" />

          <div className="td-analysis__block">
            <p className="td-analysis__label">Current status</p>
            <p className="td-analysis__value">
              {thread.analysis?.current_status ?? "—"}
            </p>
          </div>

          <div className="td-analysis__block td-analysis__block--accent">
            <p className="td-analysis__label">Next action</p>
            <p className="td-analysis__value td-analysis__value--strong">
              {thread.analysis?.next_action ?? "Open the conversation and decide the next step."}
            </p>
          </div>

          <div className="td-analysis__divider" />

          <div className="td-analysis__facts">
            <div className="td-analysis__fact">
              <p className="td-analysis__label">Workflow</p>
              <p className="td-analysis__value">{workflowLabel(thread)}</p>
            </div>
            <div className="td-analysis__fact">
              <p className="td-analysis__label">Verifier</p>
              <p className="td-analysis__value">
                {thread.analysis ? `${thread.analysis.accuracy_percent}%` : "—"}
              </p>
            </div>
            <div className="td-analysis__fact">
              <p className="td-analysis__label">Participants</p>
              <p className="td-analysis__value">{thread.participants.length}</p>
            </div>
          </div>

          {thread.latest_draft && (
            <>
              <div className="td-analysis__divider" />
              <DraftBlock draft={thread.latest_draft} />
            </>
          )}

          {thread.analysis?.needs_human_review && (
            <div className="td-analysis__review-flag">
              <p className="td-analysis__label">Needs review</p>
              <p className="td-analysis__value td-analysis__value--muted">
                {thread.analysis.review_reason ?? "The verifier flagged this for manual review."}
              </p>
            </div>
          )}
          </>}

        </aside>

        {/* Right: Messages */}
        <div className="td-messages">
          <p className="td-messages__label">Conversation · {thread.message_count} message{thread.message_count !== 1 ? "s" : ""}</p>
          <div className="td-messages__list">
            {thread.messages.map((message, index) => (
              <MessageTimelineItem key={message.message_id} message={message} index={index} />
            ))}
          </div>
        </div>

      </div>
    </section>
  );
}
