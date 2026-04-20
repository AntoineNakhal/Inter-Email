import { useParams } from "react-router-dom";

import { DraftComposer } from "../features/drafts/DraftComposer";
import { useSeenMutation, useThread } from "../hooks/useApi";
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

export function ThreadDetailPage() {
  const { threadId } = useParams();
  const { data: thread, isLoading, error } = useThread(threadId);
  const seenMutation = useSeenMutation(threadId ?? "");

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

        <button
          className="button button--ghost"
          onClick={() => seenMutation.mutate(!(thread.seen_state?.seen ?? false))}
        >
          {thread.seen_state?.seen ? "Mark Unseen" : "Mark Seen"}
        </button>
      </div>

      <div className="detail-grid thread-detail__grid">
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
            <p className="thread-detail__label">Next action</p>
            <p className="thread-detail__body thread-detail__body--strong">
              {thread.analysis?.next_action ??
                "Open the conversation and decide the next owner."}
            </p>
          </div>

          <div className="thread-detail__facts">
            <div className="thread-detail__fact">
              <p className="thread-detail__label">Workflow</p>
              <p className="thread-detail__body">{workflowLabel(thread)}</p>
            </div>
            <div className="thread-detail__fact">
              <p className="thread-detail__label">Draft suggested</p>
              <p className="thread-detail__body">
                {thread.analysis?.should_draft_reply ? "Yes" : "No"}
              </p>
            </div>
            <div className="thread-detail__fact">
              <p className="thread-detail__label">Date needed</p>
              <p className="thread-detail__body">
                {thread.analysis?.draft_needs_date ? "Yes" : "No"}
              </p>
            </div>
            <div className="thread-detail__fact">
              <p className="thread-detail__label">Attachment needed</p>
              <p className="thread-detail__body">
                {thread.analysis?.draft_needs_attachment ? "Yes" : "No"}
              </p>
            </div>
          </div>
        </section>

        <DraftComposer thread={thread} />
      </div>

      <section className="panel stack thread-detail__messages">
        <div className="thread-detail__section-head">
          <div>
            <p className="eyebrow">Messages</p>
            <h3>Conversation timeline</h3>
          </div>
        </div>

        <div className="thread-detail__message-list">
          {thread.messages.map((message, index) => (
            <article key={message.message_id} className="message-card message-card--thread">
              <div className="message-card__header">
                <div className="message-card__identity">
                  <strong>{formatInlineText(message.sender) || "Unknown sender"}</strong>
                  <span className="message-card__timestamp">
                    Message {index + 1} | {formatDate(message.sent_at)}
                  </span>
                </div>
                <span className="pill tone-outline">Email</span>
              </div>

              <div className="message-card__meta-block">
                <p className="thread-detail__label">Subject</p>
                <p className="message-card__subject">
                  {formatInlineText(message.subject) || "No subject"}
                </p>
              </div>

              {message.recipients.length ? (
                <div className="message-card__meta-block">
                  <p className="thread-detail__label">Recipients</p>
                  <p className="thread-detail__body">
                    {message.recipients
                      .map((recipient) => formatInlineText(recipient))
                      .join(", ")}
                  </p>
                </div>
              ) : null}

              {formatMessageExcerpt(message.cleaned_body, message.snippet) ? (
                <div className="message-card__content-block">
                  <p className="thread-detail__label">Useful excerpt</p>
                  <p className="message-card__excerpt">
                    {formatMessageExcerpt(message.cleaned_body, message.snippet)}
                  </p>
                </div>
              ) : null}
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}
