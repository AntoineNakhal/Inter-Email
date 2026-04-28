import { ThreadCard } from "../components/ThreadCard";
import { ReviewForm } from "../features/review/ReviewForm";
import { useThreads } from "../hooks/useApi";

export function ReviewPage() {
  const { data, isLoading, error } = useThreads();
  const threads = data?.threads.slice(0, 12) ?? [];

  return (
    <section className="page rp-page">

      <div className="rp-header">
        <div>
          <p className="sp-header__eyebrow">Internal</p>
          <h1 className="sp-header__title">Quality Review</h1>
          <p className="sp-header__sub">
            Flag threads that need improvement to help tune the AI workflow.
          </p>
        </div>
        {threads.length > 0 && (
          <span className="rp-header__count">{threads.length} threads</span>
        )}
      </div>

      <div className="rp-divider" />

      {isLoading ? <p className="rp-loading">Loading threads…</p> : null}
      {error instanceof Error ? <p className="rp-error">{error.message}</p> : null}

      {threads.length > 0 ? (
        <div className="rp-list">
          {threads.map((thread) => (
            <div key={thread.thread_id} className="rp-item">
              <ThreadCard thread={thread} />
              <ReviewForm thread={thread} />
            </div>
          ))}
        </div>
      ) : !isLoading ? (
        <p className="rp-empty">No threads to review yet. Run a sync first.</p>
      ) : null}

    </section>
  );
}
