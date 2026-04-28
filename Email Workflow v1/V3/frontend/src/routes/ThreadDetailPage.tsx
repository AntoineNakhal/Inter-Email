import { useState } from "react";
import { useParams } from "react-router-dom";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faEnvelope, faSquare } from "@fortawesome/free-regular-svg-icons";
import { faSquareCheck, faThumbtack } from "@fortawesome/free-solid-svg-icons";

import { DraftComposer } from "../features/drafts/DraftComposer";
import { usePinMutation, useSeenMutation, useThread } from "../hooks/useApi";
import { formatDate } from "../lib/format";
import { formatInlineText, formatMessageExcerpt } from "../lib/messageFormat";

function workflowLabel(thread: {
  analysis: { needs_action_today: boolean } | null;
  waiting_on_us: boolean;
  resolved_or_closed: boolean;
}) {
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

function workflowTone(thread: {
  analysis: { needs_action_today: boolean } | null;
  waiting_on_us: boolean;
}) {
  if (thread.analysis?.needs_action_today) {
    return "tone-urgent";
  }
  if (thread.waiting_on_us) {
    return "tone-watch";
  }
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
    <article className="message-card message-card--thread">
      <div className="message-card__header">
        <div className="message-card__identity">
          <strong>{formatInlineText(message.sender) || "Unknown sender"}</strong>
          <span className="message-card__timestamp">
            Message {index + 1} | {formatDate(message.sent_at)}
          </span>
        </div>
        <span className="pill tone-outline">Email</span>
      </div>

      <div className="message-card__meta">
        <div className="message-card__meta-row">
          <p className="thread-detail__label">Subject</p>
          <p className="message-card__subject">
            {formatInlineText(message.subject) || "No subject"}
          </p>
        </div>

        {message.recipients.length ? (
          <div className="message-card__meta-row">
            <p className="thread-detail__label">Recipients</p>
            <p className="thread-detail__body message-card__recipients">
              {message.recipients
                .map((recipient) => formatInlineText(recipient))
                .join(", ")}
            </p>
          </div>
        ) : null}
      </div>

      {excerpt ? (
        <div className="message-card__excerpt-block">
          <p className="thread-detail__label">Useful excerpt</p>
          <button
            type="button"
            className={`message-card__excerpt-button ${
              shouldClamp ? "message-card__excerpt-button--interactive" : ""
            }`}
            onClick={() => {
              if (shouldClamp) {
                setExpanded((current) => !current);
              }
            }}
            aria-expanded={shouldClamp ? expanded : undefined}
            disabled={!shouldClamp}
          >
            <p
              className={`message-card__excerpt ${
                shouldClamp && !expanded ? "message-card__excerpt--clamped" : ""
              }`}
            >
            {excerpt}
            </p>
            {shouldClamp ? (
              <span className="message-card__toggle">
                {expanded ? "Show less" : "Show more"}
              </span>
            ) : null}
          </button>
        </div>
      ) : null}
    </article>
  );
}

export function ThreadDetailPage() {
  const { threadId } = useParams();
  const { data: thread, isLoading, error } = useThread(threadId);
  const seenMutation = useSeenMutation(threadId ?? "");
  const pinMutation = usePinMutation(threadId ?? "");

  if (isLoading) {
    return <section className="page">Loading thread...</section>;
  }

  if (error instanceof Error) {
    return <section className="page">{error.message}</section>;
  }

  if (!thread) {
    return <section className="page">Thread not found.</section>;
  }

  const toneClass = workflowTone(thread);

  return (
    <section className="page stack stack--page thread-detail">
      <div className="hero hero--compact thread-detail__hero">
        <div className="thread-detail__hero-content">
          <div>
            <p className="eyebrow">Thread Detail</p>
            <h1>{formatInlineText(thread.subject) || "Untitled thread"}</h1>
          </div>

          <div className="thread-detail__hero-meta">
            <span className={`pill ${toneClass}`}>{workflowLabel(thread)}</span>
            <span className="pill tone-outline">
              {thread.analysis?.category ?? "Needs review"}
            </span>
            <span className="pill tone-outline">
              {thread.message_count} messages
            </span>
            <span className="pill tone-outline">
              {formatDate(thread.latest_message_date)}
            </span>
          </div>

          <p className="hero-copy thread-detail__hero-copy">
            {thread.participants.map((participant) => formatInlineText(participant)).join(", ") ||
              "No participants"}
          </p>
        </div>

        <div className="thread-detail__hero-actions">
          <a
            className="button button--ghost thread-detail__hero-action thread-detail__hero-action--icon thread-detail__hero-action--unseen"
            href={gmailThreadUrl(thread.thread_id)}
            target="_blank"
            rel="noreferrer noopener"
            aria-label="Open this thread in Gmail"
            title="Open in Gmail"
          >
            <FontAwesomeIcon icon={faEnvelope} />
          </a>
          <button
            className={`button button--ghost thread-detail__hero-action thread-detail__hero-action--icon ${thread.seen_state?.seen
                ? "thread-detail__hero-action--seen"
                : "thread-detail__hero-action--unseen"
              }`}
            onClick={() => seenMutation.mutate(!(thread.seen_state?.seen ?? false))}
            aria-label={thread.seen_state?.seen ? "Undo done" : "Mark as done"}
            title={thread.seen_state?.seen ? "Undo done" : "Mark as done"}
          >
            <FontAwesomeIcon icon={thread.seen_state?.seen ? faSquareCheck : faSquare} />
          </button>
          <button
            className={`button button--ghost thread-detail__hero-action thread-detail__hero-action--icon ${thread.seen_state?.pinned
                ? "thread-detail__hero-action--pinned"
                : "thread-detail__hero-action--unseen"
              }`}
            onClick={() => pinMutation.mutate(!(thread.seen_state?.pinned ?? false))}
            aria-label={thread.seen_state?.pinned ? "Unpin thread" : "Pin thread"}
            title={thread.seen_state?.pinned ? "Unpin thread" : "Pin thread"}
          >
            <FontAwesomeIcon icon={faThumbtack} />
          </button>
        </div>
      </div>

      {/*
        Stacked vertically (instead of side-by-side) so the analysis card
        and the draft workflow no longer have to share a row — uneven
        content lengths used to make the layout look broken.
      */}
      <section className="panel stack thread-detail__analysis">
        <div className="thread-detail__section-head">
          <div>
            <p className="eyebrow">Analysis</p>
            <h3>{thread.analysis?.summary ?? "No analysis yet"}</h3>
          </div>
          <span className={`pill ${toneClass}`}>
            {thread.analysis?.urgency ?? "unknown"}
          </span>
        </div>

        <div className="thread-detail__summary-card">
          <p className="thread-detail__label">Current status</p>
          <p className="thread-detail__body">
            {thread.analysis?.current_status ?? "Run sync to analyze this thread."}
          </p>
        </div>

        <div className="thread-detail__summary-card thread-detail__summary-card--accent">
          <div className="thread-detail__next-action">
            <div className="thread-detail__next-action-copy">
              <p className="thread-detail__label">Next action</p>
              <p className="thread-detail__body thread-detail__body--strong">
                {thread.analysis?.next_action ??
                  "Open the conversation and decide the next owner."}
              </p>
            </div>
            <DraftComposer
              thread={thread}
              recommended={Boolean(thread.analysis?.should_draft_reply)}
            />
          </div>
        </div>

        <div className="thread-detail__facts">
          <div className="thread-detail__fact">
            <p className="thread-detail__label">Workflow</p>
            <p className="thread-detail__body">{workflowLabel(thread)}</p>
          </div>
          <div className="thread-detail__fact thread-detail__fact--verifier">
            <div className="thread-detail__fact-topline">
              <p className="thread-detail__label">Verifier score</p>
              {thread.analysis?.verification_summary || thread.analysis?.review_reason ? (
                <details className="thread-detail__fact-details">
                  <summary
                    className="thread-detail__fact-button"
                    aria-label="Why this verifier score?"
                  >
                    Why?
                  </summary>
                  <div className="thread-detail__fact-popover">
                    <p className="thread-detail__body">
                      {thread.analysis.verification_summary || "No verifier notes yet."}
                    </p>
                    <p className="thread-detail__body thread-detail__body--muted">
                      {thread.analysis.needs_human_review
                        ? thread.analysis.review_reason ??
                        "The verifier recommends a manual review."
                        : "The verifier is comfortable with the current analysis output."}
                    </p>
                  </div>
                </details>
              ) : null}
            </div>
            <p className="thread-detail__body">
              {thread.analysis ? `${thread.analysis.accuracy_percent}%` : "Not verified"}
            </p>
          </div>
        </div>
      </section>

      <section className="panel stack thread-detail__messages">
        <div className="thread-detail__section-head">
          <div>
            <p className="eyebrow">Messages</p>
            <h3>Conversation timeline</h3>
          </div>
        </div>

        <div className="thread-detail__message-list">
          {thread.messages.map((message, index) => (
            <MessageTimelineItem
              key={message.message_id}
              message={message}
              index={index}
            />
          ))}
        </div>
      </section>
    </section>
  );
}
