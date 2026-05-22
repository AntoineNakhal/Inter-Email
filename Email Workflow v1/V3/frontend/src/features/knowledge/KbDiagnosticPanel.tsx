import { useState } from "react";

import { apiClient } from "../../api/client";
import type { KbDiagnoseResponse } from "../../types/api";

/**
 * In-app RAG diagnostic. Runs the same `/api/v1/knowledge/diagnose`
 * endpoint as the URL we were copy-pasting into the browser before, but
 * routed through the authenticated apiClient so cookie auth always works
 * (the browser address bar doesn't always send the auth cookie cross-port
 * because of SameSite policy).
 *
 * Lives on the Technical Info page as a "Diagnose RAG" affordance so any
 * user wondering "did the AI actually look at my docs?" has a one-click
 * answer rather than having to wade through container logs.
 */
export function KbDiagnosticPanel() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<KbDiagnoseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    const trimmed = query.trim();
    if (!trimmed) {
      setError("Enter a query to test (e.g. a product name or spec).");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const response = await apiClient.diagnoseRag(trimmed);
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Diagnostic failed.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const verdictTone = result
    ? result.verdict.startsWith("OK")
      ? "tone-positive"
      : result.verdict.startsWith("WARN")
        ? "tone-watch"
        : "tone-urgent"
    : "tone-neutral";

  return (
    <div className="sp-section">
      <div className="sp-section__head">
        <div>
          <p className="sp-label">Diagnostic</p>
          <p className="sp-section__title">Test RAG retrieval</p>
        </div>
      </div>
      <p className="sp-hint">
        Type a sample question — usually the kind of thing an email would
        ask — and see whether RAG would find anything for it. Useful when
        a draft says "no sources used" and you want to know why.
      </p>

      <div className="kb-diag__row">
        <input
          type="text"
          className="kb-diag__input"
          placeholder="e.g. transportable stake antenna windload"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              run();
            }
          }}
        />
        <button
          type="button"
          className="kb-btn kb-btn--primary"
          onClick={run}
          disabled={loading}
        >
          {loading ? "Running…" : "Run diagnostic"}
        </button>
      </div>

      {error ? <p className="sp-alert">{error}</p> : null}

      {result ? (
        <div className="kb-diag__result">
          <p className={`pill ${verdictTone}`}>{result.verdict}</p>

          <dl className="kb-diag__facts">
            <div>
              <dt>KB enabled</dt>
              <dd>{result.kb_enabled ? "yes" : "no"}</dd>
            </div>
            <div>
              <dt>Session open</dt>
              <dd>{result.kb_session_open ? "yes" : "no"}</dd>
            </div>
            <div>
              <dt>Documents (ready)</dt>
              <dd>{result.documents_ready}</dd>
            </div>
            <div>
              <dt>Total chunks</dt>
              <dd>{result.chunks_total.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Embedding</dt>
              <dd>
                {result.embedding_succeeded
                  ? `${result.embedding_dim}-dim vector`
                  : "failed"}
              </dd>
            </div>
            <div>
              <dt>Threshold</dt>
              <dd>{result.threshold.toFixed(2)}</dd>
            </div>
            <div>
              <dt>Above threshold</dt>
              <dd>
                {result.matches_above_threshold.length} / {result.unfiltered_matches.length}
              </dd>
            </div>
          </dl>

          {result.unfiltered_matches.length > 0 ? (
            <div className="kb-diag__matches">
              <p className="sp-label">Top candidates</p>
              <ul>
                {result.unfiltered_matches.map((match) => (
                  <li key={match.chunk_id} className="kb-diag__match">
                    <div className="kb-diag__match-head">
                      <span className="kb-diag__match-sim">
                        {(match.similarity * 100).toFixed(1)}%
                      </span>
                      <span className="kb-diag__match-title">
                        {match.document_title}
                      </span>
                      <span className="kb-diag__match-tag">
                        Chunk #{match.chunk_index}
                      </span>
                      {match.similarity >= result.threshold ? (
                        <span className="pill tone-positive kb-diag__match-pill">
                          above threshold
                        </span>
                      ) : (
                        <span className="pill tone-neutral kb-diag__match-pill">
                          below
                        </span>
                      )}
                    </div>
                    <p className="kb-diag__match-preview">{match.preview}</p>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="sp-hint">
              No candidates returned by pgvector. This usually means the
              corpus is empty or every document is in a non-READY state.
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}
