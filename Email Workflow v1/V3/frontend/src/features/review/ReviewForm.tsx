import { useState } from "react";

import { useReviewMutation } from "../../hooks/useApi";
import type { EmailThread } from "../../types/api";

type ReviewFormProps = {
  thread: EmailThread;
};

export function ReviewForm({ thread }: ReviewFormProps) {
  const mutation = useReviewMutation(thread.thread_id);
  const [notes, setNotes] = useState(thread.review?.notes ?? "");
  const [queueBelongs, setQueueBelongs] = useState(
    thread.review?.queue_belongs ?? "not_sure",
  );
  const [mergeCorrect, setMergeCorrect] = useState(
    thread.review?.merge_correct ?? "not_sure",
  );

  return (
    <form
      className="review-form"
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate({
          queue_belongs: queueBelongs,
          merge_correct: mergeCorrect,
          summary_useful: thread.review?.summary_useful ?? "partially",
          next_action_useful: thread.review?.next_action_useful ?? "partially",
          draft_useful: thread.review?.draft_useful ?? "partially",
          crm_useful: thread.review?.crm_useful ?? "not_applicable",
          notes,
          improvement_tags: thread.review?.improvement_tags ?? [],
        });
      }}
    >
      <div className="review-grid">
        <label>
          Queue belongs
          <select
            value={queueBelongs}
            onChange={(event) => setQueueBelongs(event.target.value)}
          >
            <option value="yes">Yes</option>
            <option value="no">No</option>
            <option value="not_sure">Not sure</option>
          </select>
        </label>

        <label>
          Merge correct
          <select
            value={mergeCorrect}
            onChange={(event) => setMergeCorrect(event.target.value)}
          >
            <option value="yes">Yes</option>
            <option value="no">No</option>
            <option value="not_sure">Not sure</option>
          </select>
        </label>
      </div>

      <label>
        Notes
        <textarea
          rows={4}
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="What should improve in the analysis or workflow?"
        />
      </label>

      <button className="button" type="submit" disabled={mutation.isPending}>
        {mutation.isPending ? "Saving..." : "Save Review"}
      </button>
    </form>
  );
}
