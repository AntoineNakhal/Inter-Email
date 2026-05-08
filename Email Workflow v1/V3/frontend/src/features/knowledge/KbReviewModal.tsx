import { useEffect, useMemo, useState } from "react";

import {
  useDeleteKbDocumentMutation,
  useFinalizeKbDocumentMutation,
  useKbDocument,
} from "../../hooks/useApi";
import type { KbDocument } from "../../types/api";
import { KbChunkExplorer } from "./KbChunkExplorer";

type KbReviewModalProps = {
  documentId: number;
  /** Called after the user successfully saves OR cancels — clears the modal. */
  onClose: () => void;
};

/**
 * Human-in-the-loop review for newly uploaded KB documents.
 *
 * Flow:
 *  1) Modal opens immediately after upload (status: pending/processing).
 *  2) `useKbDocument` polls every 1.5 s while the worker chunks/embeds.
 *  3) When status flips to `awaiting_review`, the form fields auto-populate
 *     with what Haiku extracted. The user can edit anything.
 *  4) Save → POST finalize → status becomes `ready`, doc enters RAG.
 *  5) Cancel → DELETE the doc + chunks; nothing leaks into RAG.
 *
 * Important UX guarantees:
 *  - Save is disabled until extraction completes (status awaiting_review).
 *  - Cancel works at any point so a stuck upload can always be removed.
 *  - On `failed` status, we surface the error and show only Delete + Close.
 */
export function KbReviewModal({ documentId, onClose }: KbReviewModalProps) {
  const { data: document, error } = useKbDocument(documentId);
  const finalizeMutation = useFinalizeKbDocumentMutation();
  const deleteMutation = useDeleteKbDocumentMutation();

  // Hydrate the form once the worker has produced metadata. We track
  // hydration so subsequent polling refetches don't blow away the user's
  // in-progress edits.
  const [form, setForm] = useState<FormState | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!document) return;
    if (form !== null) return;
    if (
      document.status === "awaiting_review" ||
      document.status === "ready"
    ) {
      setForm({
        title: document.title || document.filename,
        product_name: document.product_name ?? "",
        category: document.category ?? "",
        description: document.description ?? "",
      });
    }
  }, [document, form]);

  const isReadyToReview = document?.status === "awaiting_review" ||
    document?.status === "ready";
  const isProcessing =
    document?.status === "pending" || document?.status === "processing";
  const isFailed = document?.status === "failed";

  const onSave = async () => {
    if (!form || !document) return;
    setSubmitError(null);
    try {
      await finalizeMutation.mutateAsync({
        documentId: document.id,
        payload: {
          title: form.title.trim(),
          product_name: blankToNull(form.product_name),
          category: blankToNull(form.category),
          description: blankToNull(form.description),
        },
      });
      onClose();
    } catch (mutationError) {
      setSubmitError(
        mutationError instanceof Error
          ? mutationError.message
          : "Failed to save document.",
      );
    }
  };

  const onCancel = async () => {
    if (!document) {
      onClose();
      return;
    }
    setSubmitError(null);
    try {
      await deleteMutation.mutateAsync(document.id);
    } catch (mutationError) {
      setSubmitError(
        mutationError instanceof Error
          ? mutationError.message
          : "Failed to delete document.",
      );
      return;
    }
    onClose();
  };

  return (
    <div
      className="kb-modal__backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="kb-modal-title"
      onClick={(event) => {
        // Click on backdrop (not on the modal itself) acts like Cancel —
        // but only when nothing is mid-mutation, so we don't drop a save.
        if (
          event.target === event.currentTarget &&
          !finalizeMutation.isPending &&
          !deleteMutation.isPending
        ) {
          onCancel();
        }
      }}
    >
      <div className="kb-modal" onClick={(event) => event.stopPropagation()}>
        <header className="kb-modal__head">
          <div>
            <p className="sp-label">Review document</p>
            <h2 id="kb-modal-title" className="kb-modal__title">
              {document?.filename ?? "Uploading…"}
            </h2>
          </div>
          <StatusBadge document={document} hasError={Boolean(error)} />
        </header>

        <ReadOnlyMeta document={document} />

        {isProcessing ? (
          <ProcessingPanel />
        ) : isFailed ? (
          <FailedPanel
            errorMessage={document?.error_message ?? "Ingestion failed."}
          />
        ) : isReadyToReview && form ? (
          <div className="kb-modal__split">
            <section className="kb-modal__col">
              <h3 className="kb-modal__col-title">Document details</h3>
              <ReviewForm form={form} onChange={setForm} />
            </section>
            <section className="kb-modal__col kb-modal__col--chunks">
              <h3 className="kb-modal__col-title">
                Extracted chunks
                <span className="sp-hint" style={{ marginLeft: "0.5rem", fontWeight: 400 }}>
                  — what the AI will actually search
                </span>
              </h3>
              <KbChunkExplorer documentId={documentId} enabled={true} />
            </section>
          </div>
        ) : error ? (
          <p className="sp-alert">
            {error instanceof Error ? error.message : "Failed to load document."}
          </p>
        ) : null}

        {submitError ? (
          <p className="sp-alert" role="alert">
            {submitError}
          </p>
        ) : null}

        <footer className="kb-modal__foot">
          <button
            type="button"
            className="kb-btn"
            onClick={onCancel}
            disabled={deleteMutation.isPending || finalizeMutation.isPending}
          >
            {deleteMutation.isPending ? "Cancelling…" : "Cancel"}
          </button>
          <button
            type="button"
            className="kb-btn kb-btn--primary"
            onClick={onSave}
            disabled={
              !isReadyToReview ||
              finalizeMutation.isPending ||
              deleteMutation.isPending ||
              !form?.title.trim()
            }
          >
            {finalizeMutation.isPending ? "Saving…" : "Save"}
          </button>
        </footer>
      </div>
    </div>
  );
}

// ─── Sub-components ─────────────────────────────────────────────────────
function StatusBadge({
  document,
  hasError,
}: {
  document: KbDocument | undefined;
  hasError: boolean;
}) {
  if (hasError) return <span className="pill tone-urgent">Error</span>;
  if (!document) return <span className="pill tone-neutral">Loading…</span>;
  const config: Record<KbDocument["status"], { label: string; tone: string }> = {
    pending: { label: "Queued", tone: "tone-neutral" },
    processing: { label: "Extracting", tone: "tone-watch" },
    awaiting_review: { label: "Ready to review", tone: "tone-positive" },
    ready: { label: "Saved", tone: "tone-positive" },
    failed: { label: "Failed", tone: "tone-urgent" },
  };
  const { label, tone } = config[document.status];
  return <span className={`pill ${tone}`}>{label}</span>;
}

function ReadOnlyMeta({ document }: { document: KbDocument | undefined }) {
  if (!document) return null;
  const meta = useMemo(
    () =>
      [
        document.file_type.toUpperCase(),
        formatSize(document.size_bytes),
        document.status === "awaiting_review" || document.status === "ready"
          ? `${document.chunk_count} chunk${document.chunk_count === 1 ? "" : "s"}`
          : null,
      ].filter(Boolean),
    [document],
  );
  return (
    <p className="kb-modal__meta">
      {meta.map((part, index) => (
        <span key={index}>{part}</span>
      ))}
    </p>
  );
}

function ProcessingPanel() {
  return (
    <div className="kb-modal__panel">
      <div className="kb-spinner" aria-hidden="true" />
      <div>
        <p className="kb-modal__panel-title">Extracting metadata…</p>
        <p className="sp-hint">
          We're reading your file, splitting it into searchable chunks, and
          asking the AI for a draft title, product, and description.
        </p>
      </div>
    </div>
  );
}

function FailedPanel({ errorMessage }: { errorMessage: string }) {
  return (
    <div className="kb-modal__panel kb-modal__panel--err">
      <p className="kb-modal__panel-title">Ingestion failed</p>
      <p className="sp-alert">{errorMessage}</p>
      <p className="sp-hint">
        Cancel to remove this document and try uploading again.
      </p>
    </div>
  );
}

type FormState = {
  title: string;
  product_name: string;
  category: string;
  description: string;
};

function ReviewForm({
  form,
  onChange,
}: {
  form: FormState;
  onChange: (next: FormState) => void;
}) {
  return (
    <div className="kb-modal__form">
      <p className="sp-hint">
        Review what was extracted and edit anything that's wrong. Saving makes
        this document searchable in AI replies and analyses.
      </p>
      <label className="sp-field">
        <span className="sp-field__label">Title</span>
        <input
          type="text"
          value={form.title}
          onChange={(event) =>
            onChange({ ...form, title: event.target.value })
          }
          maxLength={500}
        />
      </label>
      <label className="sp-field">
        <span className="sp-field__label">Product name</span>
        <input
          type="text"
          value={form.product_name}
          onChange={(event) =>
            onChange({ ...form, product_name: event.target.value })
          }
          maxLength={255}
          placeholder="e.g. ACME-X20"
        />
      </label>
      <label className="sp-field">
        <span className="sp-field__label">Category</span>
        <input
          type="text"
          value={form.category}
          onChange={(event) =>
            onChange({ ...form, category: event.target.value })
          }
          maxLength={255}
          placeholder="datasheet, user manual, install guide…"
        />
      </label>
      <label className="sp-field">
        <span className="sp-field__label">Description</span>
        <textarea
          rows={4}
          value={form.description}
          onChange={(event) =>
            onChange({ ...form, description: event.target.value })
          }
          placeholder="One or two sentences summarizing the document."
        />
      </label>
    </div>
  );
}

// ─── helpers ────────────────────────────────────────────────────────────
function blankToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function formatSize(bytes: number): string {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}
