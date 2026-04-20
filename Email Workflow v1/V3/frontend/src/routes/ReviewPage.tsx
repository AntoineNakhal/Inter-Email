import { ThreadCard } from "../components/ThreadCard";
import { ReviewForm } from "../features/review/ReviewForm";
import { useThreads } from "../hooks/useApi";

export function ReviewPage() {
  const { data, isLoading, error } = useThreads();

  return (
    <section className="page stack">
      <div className="hero hero--compact">
        <div>
          <p className="eyebrow">Internal Review</p>
          <h1>Quality Review Queue</h1>
        </div>
      </div>

      {isLoading ? <p>Loading threads...</p> : null}
      {error instanceof Error ? <p>{error.message}</p> : null}

      <div className="review-list">
        {data?.threads.slice(0, 12).map((thread) => (
          <section key={thread.thread_id} className="review-card">
            <ThreadCard thread={thread} />
            <ReviewForm thread={thread} />
          </section>
        ))}
      </div>
    </section>
  );
}
