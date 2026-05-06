import { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { Link, useNavigate, useParams } from "react-router-dom";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faEnvelope, faSquare } from "@fortawesome/free-regular-svg-icons";
import { faArrowLeft, faCopy, faPaperPlane, faScissors, faSliders, faSquareCheck, faThumbtack, faWandMagicSparkles } from "@fortawesome/free-solid-svg-icons";

import { DraftComposer } from "../features/drafts/DraftComposer";
import { OverrideModal } from "../features/overrides/OverrideModal";
import { useAnalyzeMutation, useDeleteDraftMutation, useDeleteOverrideMutation, usePinMutation, useSaveOverrideMutation, useSeenMutation, useSplitThreadMutation, useThread } from "../hooks/useApi";
import { formatDate } from "../lib/format";
import { formatInlineText, formatMessageExcerpt } from "../lib/messageFormat";

function hasDraftContent(
  draft: { subject: string; body: string } | null | undefined,
): draft is { subject: string; body: string } {
  if (!draft) return false;
  return draft.subject.trim().length > 0 || draft.body.trim().length > 0;
}

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

function DraftBlock({
  draft,
  threadId,
  participants,
}: {
  draft: { subject: string; body: string };
  threadId: string;
  participants: string[];
}) {
  const queryClient = useQueryClient();
  const deleteDraft = useDeleteDraftMutation(threadId);
  const [copied, setCopied] = useState(false);
  const [confirmSend, setConfirmSend] = useState(false);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  function copy() {
    navigator.clipboard.writeText(draft.body).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }

  async function send() {
    const to = participants.find((p) => p.includes("@") && !p.includes("inter-op.ca")) ?? participants[0] ?? "";
    setSending(true);
    setSendError(null);
    try {
      await apiClient.sendDraft(threadId, { subject: draft.subject, body: draft.body, to });
      setConfirmSend(false);
      setSent(true);
      await Promise.all([
        queryClient.refetchQueries({ queryKey: ["thread", threadId] }),
        queryClient.invalidateQueries({ queryKey: ["queue-dashboard"] }),
      ]);
    } catch (err) {
      setSendError(err instanceof Error ? err.message : "Send failed.");
    } finally {
      setSending(false);
    }
  }

  function handleSendClick() {
    if (sending || sent) return;
    if (!confirmSend) {
      setSendError(null);
      setConfirmSend(true);
      return;
    }
    void send();
  }

  return (
    <div className="td-analysis__draft">
      <div className="td-analysis__draft-header">
        <p className="td-analysis__label">Generated draft</p>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <button
            className={`td-analysis__draft-send${confirmSend ? " td-analysis__draft-send--confirm" : ""}`}
            type="button"
            onClick={handleSendClick}
            disabled={sending || sent}
            title={sent ? "Sent" : confirmSend ? "Click again to confirm send" : "Send via Gmail"}
          >
            <FontAwesomeIcon icon={faPaperPlane} />
            {sending ? "Sending…" : sent ? "Sent ✓" : "Send"}
          </button>
          {confirmSend && !sending && !sent ? (
            <button
              className="td-analysis__draft-cancel"
              type="button"
              onClick={() => setConfirmSend(false)}
              title="Cancel send"
            >
              Cancel
            </button>
          ) : null}
          <button
            className="td-analysis__draft-delete"
            type="button"
            onClick={() => deleteDraft.mutate()}
            disabled={deleteDraft.isPending}
            title="Discard draft"
          >
            {deleteDraft.isPending ? "…" : "✕"}
          </button>
        </div>
      </div>
      <p className="td-analysis__draft-subject">{draft.subject}</p>
      <div className="td-analysis__draft-body-wrap">
        <button
          className={`td-analysis__draft-copy${copied ? " td-analysis__draft-copy--copied" : ""}`}
          type="button"
          onClick={copy}
          title="Copy"
        >
          <FontAwesomeIcon icon={faCopy} />
        </button>
        <pre className="td-analysis__draft-body">{draft.body}</pre>
      </div>
      {sendError && <p style={{ fontSize: "0.75rem", color: "var(--alert)", margin: 0 }}>{sendError}</p>}
    </div>
  );
}

export function ThreadDetailPage() {
  const { threadId } = useParams();
  const navigate = useNavigate();
  const { data: thread, isLoading, error } = useThread(threadId);
  const seenMutation = useSeenMutation(threadId ?? "");
  const pinMutation = usePinMutation(threadId ?? "");
  const analyzeMutation = useAnalyzeMutation(threadId ?? "");
  const saveOverride = useSaveOverrideMutation(threadId ?? "");
  const deleteOverride = useDeleteOverrideMutation(threadId ?? "");
  const splitThread = useSplitThreadMutation(threadId ?? "");
  const [showOverrideModal, setShowOverrideModal] = useState(false);

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
        </div>

        <div className="td-header__title-row">
          <h1 className="td-header__subject">
            {formatInlineText(thread.subject) || "Untitled thread"}
          </h1>
          <button
            className={`td-icon-action ${thread.seen_state?.pinned ? "td-icon-action--active" : ""}`}
            onClick={() => pinMutation.mutate(!(thread.seen_state?.pinned ?? false))}
            aria-label={thread.seen_state?.pinned ? "Unpin" : "Pin"}
            title={thread.seen_state?.pinned ? "Unpin" : "Pin"}
          >
            <FontAwesomeIcon icon={faThumbtack} />
          </button>
        </div>

        <div className="td-header__meta">
          <span className={`pill ${toneClass}`}>{workflowLabel(thread)}</span>
          {thread.analysis?.urgency && thread.analysis.urgency !== "unknown" && (
            <span className="pill tone-outline">{thread.analysis.urgency}</span>
          )}
          <span className="pill tone-outline">{thread.analysis?.category ?? "Needs review"}</span>
          {thread.override && (
            <span className="pill tone-override" title="You have manual overrides on this thread">
              ✎ Overridden
            </span>
          )}
          {(thread.source_thread_ids?.length ?? 0) > 1 && (
            <span className="pill tone-outline td-merged-pill" title={`Merge signals: ${thread.merge_signals?.join(", ")}`}>
              ⊕ Merged · {thread.source_thread_ids.length} threads
              <button
                className="td-merged-pill__split"
                onClick={() => {
                  if (confirm("Split this merged thread back into its original Gmail threads?")) {
                    splitThread.mutate(undefined, { onSuccess: () => navigate("/inbox") });
                  }
                }}
                disabled={splitThread.isPending}
                title="Split thread"
              >
                <FontAwesomeIcon icon={faScissors} />
              </button>
            </span>
          )}
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

          {/* Analyse + Override inline actions */}
          <div className="td-analysis__toolbar">
            <button
              className={`td-analysis__tool-btn${analyzeMutation.isPending ? " td-analysis__tool-btn--active" : ""}`}
              onClick={() => analyzeMutation.mutate()}
              disabled={analyzeMutation.isPending}
              title={analyzeMutation.isPending ? "Analysing…" : "Re-analyse with AI"}
            >
              <FontAwesomeIcon icon={faWandMagicSparkles} style={analyzeMutation.isPending ? { animation: "spin 1s linear infinite" } : undefined} />
              {analyzeMutation.isPending ? "Analysing…" : "Analyse"}
            </button>
            <button
              className={`td-analysis__tool-btn${thread.override ? " td-analysis__tool-btn--override" : ""}`}
              onClick={() => setShowOverrideModal(true)}
              title={thread.override ? "Edit your overrides" : "Override AI fields"}
            >
              <FontAwesomeIcon icon={faSliders} />
              {thread.override ? "Overrides ✎" : "Override"}
            </button>
          </div>

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
            <p className="td-analysis__summary td-analysis__summary--empty">No analysis yet — click Analyse above.</p>
          )}

          {!analyzeMutation.isPending && <><div className="td-analysis__divider" />

          <div className="td-analysis__block">
            <p className="td-analysis__label">Current status</p>
            <p className="td-analysis__value">
              {thread.analysis?.current_status ?? "—"}
            </p>
          </div>

          <div className="td-analysis__block td-analysis__block--accent">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <p className="td-analysis__label">Next action</p>
              <button
                className={`td-icon-action ${thread.seen_state?.seen ? "td-icon-action--active" : ""}`}
                onClick={() => seenMutation.mutate(!(thread.seen_state?.seen ?? false))}
                aria-label={thread.seen_state?.seen ? "Undo done" : "Mark as done"}
                title={thread.seen_state?.seen ? "Undo done" : "Mark done"}
                style={{ flexShrink: 0 }}
              >
                <FontAwesomeIcon icon={thread.seen_state?.seen ? faSquareCheck : faSquare} />
              </button>
            </div>
            <p className="td-analysis__value td-analysis__value--strong">
              {thread.analysis?.needs_next_action
                ? thread.analysis.next_action
                : "No action needed right now."}
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

          <div className="td-analysis__divider" />
          {hasDraftContent(thread.latest_draft) ? (
            <DraftBlock draft={thread.latest_draft} threadId={thread.thread_id} participants={thread.participants} />
          ) : thread.analysis?.should_draft_reply ? (
            <div className="td-analysis__draft-empty">
              <div className="td-analysis__draft-empty-header">
                <p className="td-analysis__label">Draft reply</p>
                <DraftComposer thread={thread} recommended />
              </div>
              <p className="td-analysis__draft-empty-hint">
                AI recommends drafting a reply for this thread.
              </p>
            </div>
          ) : (
            <div className="td-analysis__draft-empty td-analysis__draft-empty--muted">
              <div className="td-analysis__draft-empty-header">
                <p className="td-analysis__label">Draft reply</p>
                <DraftComposer thread={thread} recommended={false} />
              </div>
              <p className="td-analysis__draft-empty-hint">
                No reply needed — generate one anyway if required.
              </p>
            </div>
          )}

          {thread.analysis?.needs_human_review && (
            <div className="td-analysis__review-flag">
              <p className="td-analysis__label">Needs review</p>
              <p className="td-analysis__value td-analysis__value--muted">
                {thread.analysis.review_reason ?? "The verifier flagged this for manual review."}
              </p>
            </div>
          )}

          {/* Override panel */}
          {thread.override && !thread.override.category === false || thread.override ? (
            <>
              <div className="td-analysis__divider" />
              <div className="td-analysis__override-panel">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <p className="td-analysis__label">Your overrides</p>
                  <button
                    className="td-analysis__override-edit"
                    onClick={() => setShowOverrideModal(true)}
                    title="Edit overrides"
                  >
                    Edit
                  </button>
                </div>
                {thread.override?.category && (
                  <p className="td-analysis__value td-analysis__value--muted">
                    Category: <strong>{thread.override.category}</strong>
                    {thread.analysis?.ai_override_disagreements?.["category"] && (
                      <span className="override-disagree" title={thread.analysis.ai_override_disagreements["category"]}> ⚠ AI disagrees</span>
                    )}
                  </p>
                )}
                {thread.override?.urgency && (
                  <p className="td-analysis__value td-analysis__value--muted">
                    Urgency: <strong>{thread.override.urgency}</strong>
                    {thread.analysis?.ai_override_disagreements?.["urgency"] && (
                      <span className="override-disagree" title={thread.analysis.ai_override_disagreements["urgency"]}> ⚠ AI disagrees</span>
                    )}
                  </p>
                )}
                {thread.override?.relevance_bucket && (
                  <p className="td-analysis__value td-analysis__value--muted">
                    Priority: <strong>{thread.override.relevance_bucket}</strong>
                  </p>
                )}
                {thread.override?.needs_action_today !== null && thread.override?.needs_action_today !== undefined && (
                  <p className="td-analysis__value td-analysis__value--muted">
                    Act today: <strong>{thread.override.needs_action_today ? "Yes" : "No"}</strong>
                    {thread.analysis?.ai_override_disagreements?.["needs_action_today"] && (
                      <span className="override-disagree" title={thread.analysis.ai_override_disagreements["needs_action_today"]}> ⚠ AI disagrees</span>
                    )}
                  </p>
                )}
                {thread.override?.notes && (
                  <p className="td-analysis__value td-analysis__value--muted" style={{ fontStyle: "italic", marginTop: "0.25rem" }}>
                    "{thread.override.notes}"
                  </p>
                )}
              </div>
            </>
          ) : null}
          </>}

        </aside>

        {/* Right: Messages */}
        <div className="td-messages">
          <div className="td-messages__header">
            <p className="td-messages__label">Conversation · {thread.message_count} message{thread.message_count !== 1 ? "s" : ""}</p>
            <a
              className="td-icon-action"
              href={gmailThreadUrl(thread.thread_id)}
              target="_blank"
              rel="noreferrer noopener"
              aria-label="Open in Gmail"
              title="Open in Gmail"
            >
              <FontAwesomeIcon icon={faEnvelope} />
            </a>
          </div>
          <div className="td-messages__list">
            {thread.messages.map((message, index) => (
              <MessageTimelineItem key={message.message_id} message={message} index={index} />
            ))}
          </div>
        </div>

      </div>

      {showOverrideModal && (
        <OverrideModal
          threadId={thread.thread_id}
          current={thread.override}
          analysis={thread.analysis}
          disagreements={thread.analysis?.ai_override_disagreements ?? {}}
          onSave={(payload) => {
            saveOverride.mutate(payload, { onSuccess: () => setShowOverrideModal(false) });
          }}
          onClear={() => {
            deleteOverride.mutate(undefined, { onSuccess: () => setShowOverrideModal(false) });
          }}
          onClose={() => setShowOverrideModal(false)}
          isSaving={saveOverride.isPending}
          isClearing={deleteOverride.isPending}
        />
      )}
    </section>
  );
}
