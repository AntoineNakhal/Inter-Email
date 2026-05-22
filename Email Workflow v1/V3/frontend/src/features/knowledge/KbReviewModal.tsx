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
        search_aliases: document.search_aliases ?? "",
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
          search_aliases: form.search_aliases.trim(),
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
          <ProcessingPanel document={document} />
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

// ── Processing progress bar ──────────────────────────────────────────────

type ProgressStep = KbDocument["progress_step"];

const STEPS: ProgressStep[] = [
  "extracting",
  "chunking",
  "embedding",
  "persisting",
  "metadata",
];

const STEP_LABELS: Record<NonNullable<ProgressStep>, string> = {
  extracting: "Reading file",
  chunking: "Splitting into chunks",
  embedding: "Generating embeddings",
  persisting: "Saving chunks",
  metadata: "Extracting metadata",
};

// Target fill % when a step is reached. We animate smoothly toward the
// next target between polls (1.5 s interval) so the bar never looks frozen.
const STEP_TARGET: Record<NonNullable<ProgressStep>, number> = {
  extracting: 20,
  chunking: 42,
  embedding: 70,
  persisting: 88,
  metadata: 96,
};

function ProcessingPanel({ document }: { document: KbDocument | undefined }) {
  const step = document?.progress_step ?? null;
  const isVideo = document?.file_type === "video";

  // Smoothly interpolate toward the current step's target percentage.
  // When the step advances we jump to the new target floor and continue.
  const target = step ? STEP_TARGET[step] : 5;
  const [fill, setFill] = useState(target);

  useEffect(() => {
    // Immediately move fill toward target, then keep inching forward
    // so the bar never looks frozen while waiting for the next poll.
    setFill((prev) => Math.max(prev, target));
    const id = setInterval(() => {
      setFill((prev) => {
        const ceiling = target + 8; // small lookahead within the current step
        if (prev >= ceiling) return prev;
        return Math.min(prev + 0.4, ceiling);
      });
    }, 120);
    return () => clearInterval(id);
  }, [target]);

  const stepIndex = step ? STEPS.indexOf(step) : -1;

  return (
    <div className="kb-progress">
      <div className="kb-progress__bar-wrap" role="progressbar" aria-valuenow={Math.round(fill)} aria-valuemin={0} aria-valuemax={100}>
        <div className="kb-progress__bar" style={{ width: `${fill}%` }} />
      </div>

      <p className="kb-progress__label">
        {step ? STEP_LABELS[step] : "Queued…"}
      </p>

      <ol className="kb-progress__steps">
        {STEPS.map((s, i) => {
          const isDone = stepIndex > i;
          const isActive = stepIndex === i;
          return (
            <li
              key={s}
              className={`kb-progress__step${isDone ? " kb-progress__step--done" : ""}${isActive ? " kb-progress__step--active" : ""}`}
            >
              <span className="kb-progress__step-dot" />
              <span className="kb-progress__step-name">{STEP_LABELS[s!]}</span>
            </li>
          );
        })}
      </ol>

      {isVideo && (
        <p className="kb-progress__hint">
          Video files take a few minutes — audio transcription and frame
          extraction run before chunking.
        </p>
      )}
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
  search_aliases: string;
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
      <label className="sp-field">
        <span className="sp-field__label">
          Search aliases (alternate names, customer terms, synonyms)
        </span>
        <textarea
          rows={3}
          value={form.search_aliases}
          onChange={(event) =>
            onChange({ ...form, search_aliases: event.target.value })
          }
          placeholder="HF tactical deployable, portable HF antenna, deployable field antenna"
        />
        <span className="sp-hint" style={{ marginTop: "0.3rem" }}>
          Comma-separated terms a customer might use that don't appear in
          the document itself. Editing this re-embeds every chunk, so it
          may take a few seconds when saving.
        </span>
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
