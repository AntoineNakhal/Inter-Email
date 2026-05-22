import { useCallback, useMemo, useRef, useState } from "react";

import {
  useDeleteKbDocumentMutation,
  useIngestYouTubeMutation,
  useKbDocuments,
  useUploadKbDocumentMutation,
} from "../../hooks/useApi";
import type { KbDocument, KbIngestionStatus } from "../../types/api";
import { KbReviewModal } from "./KbReviewModal";

const ACCEPTED_EXTENSIONS = [
  ".pdf",
  ".pptx",
  ".xlsx",
  ".txt",
  ".md",
  ".mp4",
  ".mov",
  ".webm",
  ".mkv",
  ".m4v",
];
const ACCEPTED_FILES_LABEL =
  "PDF, PowerPoint, Excel, TXT, Markdown · MP4, MOV, WEBM, MKV";

/**
 * Drag-and-drop uploader + document list with a human-in-the-loop review
 * step. Every upload opens the `KbReviewModal`: the worker extracts
 * metadata, the user verifies/edits, then Save commits the doc into RAG.
 *
 * Implementation notes:
 *   * `reviewDocumentId` is the single source of truth for "modal is open".
 *     It's set in two places: right after a successful upload, and when
 *     the user clicks an existing AWAITING_REVIEW row in the list.
 *   * Documents are uploaded one at a time so the modal lifecycle stays
 *     simple — drop multiple files and we walk through them in order.
 */
export function KnowledgeBaseSection() {
  const { data, isLoading, error } = useKbDocuments();
  const uploadMutation = useUploadKbDocumentMutation();
  const youtubeMutation = useIngestYouTubeMutation();
  const deleteMutation = useDeleteKbDocumentMutation();

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [reviewDocumentId, setReviewDocumentId] = useState<number | null>(null);
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [youtubeError, setYoutubeError] = useState<string | null>(null);

  const documents = useMemo<KbDocument[]>(
    () => data?.documents ?? [],
    [data],
  );

  const isKbDisabled =
    error instanceof Error &&
    error.message.toLowerCase().includes("knowledge base is disabled");

  const handleFiles = useCallback(
    async (fileList: FileList | File[] | null) => {
      if (!fileList) return;
      const files = Array.from(fileList);
      if (files.length === 0) return;

      setUploadError(null);
      // Sequential to keep modal flow predictable. After each file finishes
      // ingesting + the user closes its modal, the next one's modal opens.
      for (const file of files) {
        try {
          const response = await uploadMutation.mutateAsync(file);
          setReviewDocumentId(response.document.id);
          // Wait until the modal closes before kicking off the next upload.
          // We use a Promise that resolves when reviewDocumentId clears via
          // the modal's onClose callback (handled by the polling effect
          // below — see comment in onModalClose).
          await waitForModalClose(() => reviewDocumentIdRef.current);
        } catch (mutationError) {
          setUploadError(
            mutationError instanceof Error
              ? mutationError.message
              : `Upload failed for ${file.name}`,
          );
          break;
        }
      }
    },
    [uploadMutation],
  );

  // Poll-via-ref so handleFiles can read the latest modal state without
  // re-rendering the dropzone every time the modal opens or closes.
  const reviewDocumentIdRef = useRef<number | null>(null);
  reviewDocumentIdRef.current = reviewDocumentId;

  const onDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setIsDragging(false);
      handleFiles(event.dataTransfer.files);
    },
    [handleFiles],
  );

  const onDragOver = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      if (!isDragging) setIsDragging(true);
    },
    [isDragging],
  );

  const onDragLeave = useCallback(() => setIsDragging(false), []);

  const onPickClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const onInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      handleFiles(event.target.files);
      event.target.value = "";
    },
    [handleFiles],
  );

  const onDelete = useCallback(
    async (document: KbDocument) => {
      if (pendingDeleteId !== document.id) {
        setPendingDeleteId(document.id);
        return;
      }
      try {
        await deleteMutation.mutateAsync(document.id);
      } finally {
        setPendingDeleteId(null);
      }
    },
    [deleteMutation, pendingDeleteId],
  );

  const onModalClose = useCallback(() => setReviewDocumentId(null), []);

  return (
    <div className="sp-section">
      <div className="sp-section__head">
        <div>
          <p className="sp-label">Documents</p>
          <p className="sp-section__title">Product documentation</p>
        </div>
        <span className="pill tone-neutral">
          {documents.length} {documents.length === 1 ? "doc" : "docs"}
        </span>
      </div>
      <p className="sp-hint">
        Upload product manuals and spec sheets. After upload, you'll review
        and confirm the extracted details before the doc becomes searchable.
      </p>

      {isKbDisabled ? (
        <p className="sp-alert">
          Knowledge base is disabled — set <code>KB_DATABASE_URL</code> to enable.
        </p>
      ) : (
        <>
          <div
            className={`kb-dropzone ${isDragging ? "kb-dropzone--active" : ""}`}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onClick={onPickClick}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onPickClick();
              }
            }}
          >
            <p className="kb-dropzone__title">
              {uploadMutation.isPending
                ? "Uploading…"
                : "Drop a file here, or click to choose"}
            </p>
            <p className="kb-dropzone__hint">{ACCEPTED_FILES_LABEL}</p>
            <input
              ref={fileInputRef}
              type="file"
              hidden
              accept={ACCEPTED_EXTENSIONS.join(",")}
              multiple
              onChange={onInputChange}
            />
          </div>

          {uploadError ? (
            <p className="sp-alert" role="alert">
              {uploadError}
            </p>
          ) : null}

          <div className="kb-youtube-row">
            <div className="kb-youtube-row__divider">or</div>
            <form
              className="kb-youtube-row__form"
              onSubmit={async (event) => {
                event.preventDefault();
                const trimmed = youtubeUrl.trim();
                if (!trimmed) return;
                setYoutubeError(null);
                try {
                  const response = await youtubeMutation.mutateAsync(trimmed);
                  setYoutubeUrl("");
                  setReviewDocumentId(response.document.id);
                } catch (err) {
                  setYoutubeError(
                    err instanceof Error
                      ? err.message
                      : "YouTube ingestion failed.",
                  );
                }
              }}
            >
              <input
                type="url"
                className="kb-youtube-row__input"
                placeholder="Paste a YouTube URL to ingest its audio"
                value={youtubeUrl}
                onChange={(event) => setYoutubeUrl(event.target.value)}
                disabled={youtubeMutation.isPending}
              />
              <button
                type="submit"
                className="kb-btn kb-btn--primary"
                disabled={youtubeMutation.isPending || !youtubeUrl.trim()}
              >
                {youtubeMutation.isPending
                  ? "Downloading…"
                  : "Ingest from YouTube"}
              </button>
            </form>
            {youtubeError ? (
              <p className="sp-alert" role="alert">
                {youtubeError}
              </p>
            ) : null}
          </div>

          <KbDocumentList
            documents={documents}
            isLoading={isLoading && !data}
            pendingDeleteId={pendingDeleteId}
            onDelete={onDelete}
            onCancelDelete={() => setPendingDeleteId(null)}
            onReview={setReviewDocumentId}
          />
        </>
      )}

      {reviewDocumentId !== null ? (
        <KbReviewModal
          documentId={reviewDocumentId}
          onClose={onModalClose}
        />
      ) : null}
    </div>
  );
}

// ─── Document list ──────────────────────────────────────────────────────
type KbDocumentListProps = {
  documents: KbDocument[];
  isLoading: boolean;
  pendingDeleteId: number | null;
  onDelete: (document: KbDocument) => void;
  onCancelDelete: () => void;
  onReview: (documentId: number) => void;
};

function KbDocumentList({
  documents,
  isLoading,
  pendingDeleteId,
  onDelete,
  onCancelDelete,
  onReview,
}: KbDocumentListProps) {
  if (isLoading) {
    return <p className="sp-hint">Loading documents…</p>;
  }
  if (documents.length === 0) {
    return (
      <p className="sp-hint">
        No documents yet. Drop a file above to get started.
      </p>
    );
  }
  return (
    <ul className="kb-list">
      {documents.map((document) => (
        <li key={document.id} className="kb-list__item">
          <KbDocumentRow
            document={document}
            isPendingDelete={pendingDeleteId === document.id}
            onDelete={onDelete}
            onCancelDelete={onCancelDelete}
            onReview={onReview}
          />
        </li>
      ))}
    </ul>
  );
}

// ─── Single row ─────────────────────────────────────────────────────────
type KbDocumentRowProps = {
  document: KbDocument;
  isPendingDelete: boolean;
  onDelete: (document: KbDocument) => void;
  onCancelDelete: () => void;
  onReview: (documentId: number) => void;
};

function KbDocumentRow({
  document,
  isPendingDelete,
  onDelete,
  onCancelDelete,
  onReview,
}: KbDocumentRowProps) {
  const subtitle = useMemo(
    () =>
      [
        document.product_name,
        document.category,
        document.file_type.toUpperCase(),
      ]
        .filter(Boolean)
        .join(" · "),
    [document.category, document.file_type, document.product_name],
  );
  const meta = useMemo(
    () =>
      [
        formatChunkCount(document),
        formatSize(document.size_bytes),
        formatDate(document.created_at),
      ]
        .filter(Boolean)
        .join(" · "),
    [document],
  );
  // The same modal handles both first-time review (status awaiting_review)
  // and post-hoc edits (status ready). We surface a different label for
  // each because the user intent is different — "Review" implies "I have
  // not yet approved this", "Edit" implies "I want to refine an
  // already-saved doc". Backend allows finalize on both.
  const action = openActionFor(document.status);

  return (
    <>
      <div className="kb-list__main">
        <p className="kb-list__title">{document.title || document.filename}</p>
        {subtitle ? <p className="kb-list__subtitle">{subtitle}</p> : null}
        {document.description ? (
          <p className="kb-list__desc">{document.description}</p>
        ) : null}
        <p className="kb-list__meta">{meta}</p>
        {document.status === "failed" && document.error_message ? (
          <p className="sp-alert">{document.error_message}</p>
        ) : null}
      </div>
      <div className="kb-list__actions">
        <StatusPill status={document.status} />
        {action ? (
          <button
            type="button"
            className={`kb-btn ${action.primary ? "kb-btn--primary" : ""}`}
            onClick={() => onReview(document.id)}
          >
            {action.label}
          </button>
        ) : null}
        {isPendingDelete ? (
          <>
            <button
              type="button"
              className="kb-btn kb-btn--danger"
              onClick={() => onDelete(document)}
            >
              Confirm delete
            </button>
            <button type="button" className="kb-btn" onClick={onCancelDelete}>
              Cancel
            </button>
          </>
        ) : (
          <button
            type="button"
            className="kb-btn"
            onClick={() => onDelete(document)}
          >
            Delete
          </button>
        )}
      </div>
    </>
  );
}

/**
 * Pick the right entry-point label for the modal based on document status.
 * Returns null when the row should not have an open button — typically
 * during ingestion (no metadata yet) or after a hard failure (nothing to
 * review, just delete and re-upload).
 */
function openActionFor(
  status: KbIngestionStatus,
): { label: string; primary: boolean } | null {
  switch (status) {
    case "awaiting_review":
      return { label: "Review", primary: true };
    case "ready":
      return { label: "Edit", primary: false };
    case "processing":
    case "pending":
      return { label: "View progress", primary: false };
    case "failed":
      return null;
  }
}

function StatusPill({ status }: { status: KbIngestionStatus }) {
  const config: Record<
    KbIngestionStatus,
    { label: string; tone: string }
  > = {
    pending: { label: "Pending", tone: "tone-neutral" },
    processing: { label: "Processing", tone: "tone-watch" },
    awaiting_review: { label: "Awaiting review", tone: "tone-watch" },
    ready: { label: "Ready", tone: "tone-positive" },
    failed: { label: "Failed", tone: "tone-urgent" },
  };
  const { label, tone } = config[status];
  return <span className={`pill ${tone}`}>{label}</span>;
}

// ─── helpers ────────────────────────────────────────────────────────────
function formatChunkCount(document: KbDocument): string {
  if (document.status !== "ready" && document.status !== "awaiting_review") {
    return "";
  }
  return `${document.chunk_count} chunk${document.chunk_count === 1 ? "" : "s"}`;
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

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

/**
 * Resolves once the ref reads `null` again — i.e. once the modal closes.
 * Polls every 200 ms; cheap, contained to the upload loop, and avoids
 * coupling the loop to React state via callbacks.
 */
function waitForModalClose(read: () => number | null): Promise<void> {
  return new Promise((resolve) => {
    if (read() === null) {
      resolve();
      return;
    }
    const interval = window.setInterval(() => {
      if (read() === null) {
        window.clearInterval(interval);
        resolve();
      }
    }, 200);
  });
}
