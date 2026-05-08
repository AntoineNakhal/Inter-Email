import { useDeferredValue, useMemo, useState } from "react";

import {
  useDeleteKbChunkMutation,
  useKbChunks,
  useUpdateKbChunkMutation,
} from "../../hooks/useApi";

type KbChunkExplorerProps = {
  documentId: number;
  /** Only fetch once chunks actually exist — i.e. the worker is past PROCESSING. */
  enabled: boolean;
};

/**
 * Read + edit viewer for the chunks of a single KB document.
 *
 * Why the editing capability matters: a 160-page PDF produces ~230 chunks.
 * The auto-extraction is good but not perfect — page boundaries cut
 * sentences, tables get mangled, header/footer noise creeps in. This
 * explorer lets the user fix any of that *per chunk*. Saving a chunk
 * triggers a re-embedding on the backend so the new text is searchable
 * with vectors that actually represent it.
 *
 * Performance: filter pass uses `useDeferredValue` so typing in a 230-
 * chunk doc stays responsive — React batches the filter instead of
 * running it on every keystroke.
 */
export function KbChunkExplorer({ documentId, enabled }: KbChunkExplorerProps) {
  const { data, isLoading, error } = useKbChunks(documentId, enabled);
  const updateChunkMutation = useUpdateKbChunkMutation(documentId);
  const deleteChunkMutation = useDeleteKbChunkMutation(documentId);

  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const [expandedAll, setExpandedAll] = useState(false);

  const chunks = data?.chunks ?? [];

  const filtered = useMemo(() => {
    const trimmed = deferredQuery.trim().toLowerCase();
    if (!trimmed) return chunks;
    return chunks.filter((chunk) =>
      chunk.content.toLowerCase().includes(trimmed),
    );
  }, [chunks, deferredQuery]);

  const totalTokens = useMemo(
    () => chunks.reduce((sum, c) => sum + c.token_count, 0),
    [chunks],
  );

  if (!enabled) {
    return (
      <p className="sp-hint">
        Chunks will appear here once extraction finishes.
      </p>
    );
  }
  if (isLoading) {
    return <p className="sp-hint">Loading chunks…</p>;
  }
  if (error) {
    return (
      <p className="sp-alert">
        {error instanceof Error ? error.message : "Failed to load chunks."}
      </p>
    );
  }
  if (chunks.length === 0) {
    return <p className="sp-hint">No chunks yet for this document.</p>;
  }

  return (
    <div className="kb-chunks">
      <div className="kb-chunks__head">
        <p className="sp-hint" style={{ margin: 0 }}>
          {chunks.length} chunk{chunks.length === 1 ? "" : "s"} ·{" "}
          {totalTokens.toLocaleString()} tokens total
          {filtered.length !== chunks.length
            ? ` · ${filtered.length} match${filtered.length === 1 ? "" : "es"}`
            : ""}
        </p>
        <button
          type="button"
          className="kb-btn"
          onClick={() => setExpandedAll((current) => !current)}
        >
          {expandedAll ? "Collapse all" : "Expand all"}
        </button>
      </div>

      <input
        type="search"
        className="kb-chunks__search"
        placeholder="Search inside chunks…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      <ul className="kb-chunks__list">
        {filtered.map((chunk) => (
          <ChunkCard
            key={chunk.id}
            chunk={chunk}
            highlight={deferredQuery.trim()}
            forceExpanded={expandedAll}
            onSave={(content) =>
              updateChunkMutation.mutateAsync({ chunkId: chunk.id, content })
            }
            onDelete={() => deleteChunkMutation.mutateAsync(chunk.id)}
            isSaving={
              updateChunkMutation.isPending &&
              updateChunkMutation.variables?.chunkId === chunk.id
            }
            isDeleting={
              deleteChunkMutation.isPending &&
              deleteChunkMutation.variables === chunk.id
            }
          />
        ))}
      </ul>
    </div>
  );
}

// ─── Individual chunk row ───────────────────────────────────────────────
type ChunkCardProps = {
  chunk: { id: number; chunk_index: number; content: string; token_count: number };
  highlight: string;
  forceExpanded: boolean;
  onSave: (content: string) => Promise<unknown>;
  onDelete: () => Promise<unknown>;
  isSaving: boolean;
  isDeleting: boolean;
};

function ChunkCard({
  chunk,
  highlight,
  forceExpanded,
  onSave,
  onDelete,
  isSaving,
  isDeleting,
}: ChunkCardProps) {
  const [localExpanded, setLocalExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(chunk.content);
  const [pendingDelete, setPendingDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isExpanded = forceExpanded || localExpanded;
  // Up to 280 chars / 3 lines visible in the preview — enough to make a
  // chunk's gist obvious without expanding.
  const preview = useMemo(() => previewText(chunk.content, 280), [chunk.content]);

  const onStartEdit = () => {
    setDraft(chunk.content);
    setEditing(true);
    setError(null);
  };

  const onCancelEdit = () => {
    setEditing(false);
    setError(null);
  };

  const onConfirmSave = async () => {
    const trimmed = draft.trim();
    if (!trimmed) {
      setError("Chunk content cannot be empty.");
      return;
    }
    if (trimmed === chunk.content.trim()) {
      // No-op — exit cleanly without hitting the API.
      setEditing(false);
      return;
    }
    try {
      await onSave(trimmed);
      setEditing(false);
      setError(null);
    } catch (mutationError) {
      setError(
        mutationError instanceof Error
          ? mutationError.message
          : "Failed to save chunk.",
      );
    }
  };

  const onConfirmDelete = async () => {
    try {
      await onDelete();
      setPendingDelete(false);
    } catch (mutationError) {
      setError(
        mutationError instanceof Error
          ? mutationError.message
          : "Failed to delete chunk.",
      );
      setPendingDelete(false);
    }
  };

  return (
    <li className="kb-chunks__item">
      {/* HTML spec only allows phrasing (inline) content inside <button>.
          Earlier versions used <div> and <p> here and some browsers
          auto-closed the button before the block elements — which made
          each card render as an empty 0-height strip. All children stay
          as <span>s and become block/flex via CSS instead. */}
      <button
        type="button"
        className="kb-chunks__toggle"
        onClick={() => {
          // Don't toggle while editing — accidentally collapsing the row
          // would lose the user's draft.
          if (editing) return;
          setLocalExpanded((current) => !current);
        }}
        aria-expanded={isExpanded}
      >
        <span className="kb-chunks__row">
          <span className="kb-chunks__index">Chunk #{chunk.chunk_index}</span>
          <span className="kb-chunks__tokens">{chunk.token_count} tokens</span>
        </span>
        {isExpanded ? null : (
          <span className="kb-chunks__preview">
            {highlightMatches(preview, highlight)}
          </span>
        )}
      </button>

      {isExpanded ? (
        <div className="kb-chunks__expanded">
          {editing ? (
            <>
              <textarea
                className="kb-chunks__textarea"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                rows={Math.min(20, Math.max(6, draft.split("\n").length + 1))}
                disabled={isSaving}
              />
              <p className="sp-hint">
                Saving re-runs an OpenAI embedding on this chunk so retrieval
                stays accurate. Costs about $0.000008.
              </p>
              {error ? <p className="sp-alert">{error}</p> : null}
              <div className="kb-chunks__row-actions">
                <button
                  type="button"
                  className="kb-btn"
                  onClick={onCancelEdit}
                  disabled={isSaving}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="kb-btn kb-btn--primary"
                  onClick={onConfirmSave}
                  disabled={isSaving || !draft.trim()}
                >
                  {isSaving ? "Saving…" : "Save chunk"}
                </button>
              </div>
            </>
          ) : (
            <>
              <pre className="kb-chunks__content">
                {highlightMatches(chunk.content, highlight)}
              </pre>
              {error ? <p className="sp-alert">{error}</p> : null}
              <div className="kb-chunks__row-actions">
                {pendingDelete ? (
                  <>
                    <span className="sp-hint" style={{ marginRight: "auto" }}>
                      Delete this chunk? It can't be undone.
                    </span>
                    <button
                      type="button"
                      className="kb-btn"
                      onClick={() => setPendingDelete(false)}
                      disabled={isDeleting}
                    >
                      Keep
                    </button>
                    <button
                      type="button"
                      className="kb-btn kb-btn--danger"
                      onClick={onConfirmDelete}
                      disabled={isDeleting}
                    >
                      {isDeleting ? "Deleting…" : "Confirm delete"}
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      className="kb-btn kb-btn--danger"
                      onClick={() => setPendingDelete(true)}
                      disabled={isSaving || isDeleting}
                    >
                      Delete
                    </button>
                    <button
                      type="button"
                      className="kb-btn kb-btn--primary"
                      onClick={onStartEdit}
                      disabled={isSaving || isDeleting}
                    >
                      Edit
                    </button>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      ) : null}
    </li>
  );
}

// ─── helpers ────────────────────────────────────────────────────────────
/**
 * Build a short preview for the collapsed card view. We collapse runs of
 * whitespace to single spaces (so newlines from PDF extraction don't
 * waste preview lines) but otherwise preserve the prose. Truncated with
 * an ellipsis when longer than `maxChars`.
 */
function previewText(text: string, maxChars: number): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  if (collapsed.length <= maxChars) return collapsed;
  return collapsed.slice(0, maxChars - 1).trimEnd() + "…";
}

/**
 * Lightweight inline highlighter — wraps every case-insensitive occurrence
 * of `query` in a `<mark>`. Returns the original string when query is
 * empty so React doesn't have to diff a single text node into many.
 */
function highlightMatches(text: string, query: string): React.ReactNode {
  if (!query) return text;
  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  if (!lowerText.includes(lowerQuery)) return text;

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  let position = lowerText.indexOf(lowerQuery, cursor);
  let key = 0;
  while (position !== -1) {
    if (position > cursor) parts.push(text.slice(cursor, position));
    parts.push(
      <mark key={key++} className="kb-chunks__mark">
        {text.slice(position, position + query.length)}
      </mark>,
    );
    cursor = position + query.length;
    position = lowerText.indexOf(lowerQuery, cursor);
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return parts;
}
