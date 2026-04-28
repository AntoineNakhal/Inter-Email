import { useState } from "react";

import { useReviewMutation } from "../../hooks/useApi";
import type { EmailThread } from "../../types/api";

export function ReviewForm({ thread }: { thread: EmailThread }) {
  const mutation = useReviewMutation(thread.thread_id);
  const [notes, setNotes] = useState(thread.review?.notes ?? "");
  const [queueBelongs, setQueueBelongs] = useState(thread.review?.queue_belongs ?? "not_sure");
  const [mergeCorrect, setMergeCorrect] = useState(thread.review?.merge_correct ?? "not_sure");
  const [saved, setSaved] = useState(Boolean(thread.review));

  function submit(event: React.FormEvent) {
    event.preventDefault();
    mutation.mutate(
      {
        queue_belongs: queueBelongs,
        merge_correct: mergeCorrect,
        summary_useful: thread.review?.summary_useful ?? "partially",
        next_action_useful: thread.review?.next_action_useful ?? "partially",
        draft_useful: thread.review?.draft_useful ?? "partially",
        crm_useful: thread.review?.crm_useful ?? "not_applicable",
        notes,
        improvement_tags: thread.review?.improvement_tags ?? [],
      },
      { onSuccess: () => setSaved(true) },
    );
  }

  return (
    <form className="rf-form" onSubmit={submit}>
      <div className="rf-row">
        <label className="rf-field">
          <span className="rf-label">Queue belongs</span>
          <select value={queueBelongs} onChange={(e) => { setQueueBelongs(e.target.value); setSaved(false); }}>
            <option value="yes">Yes</option>
            <option value="no">No</option>
            <option value="not_sure">Not sure</option>
          </select>
        </label>

        <label className="rf-field">
          <span className="rf-label">Merge correct</span>
          <select value={mergeCorrect} onChange={(e) => { setMergeCorrect(e.target.value); setSaved(false); }}>
            <option value="yes">Yes</option>
            <option value="no">No</option>
            <option value="not_sure">Not sure</option>
          </select>
        </label>

        <label className="rf-field rf-field--notes">
          <span className="rf-label">Notes</span>
          <input
            type="text"
            value={notes}
            onChange={(e) => { setNotes(e.target.value); setSaved(false); }}
            placeholder="What should improve?"
          />
        </label>

        <button
          className={`rf-submit${saved ? " rf-submit--saved" : ""}`}
          type="submit"
          disabled={mutation.isPending}
        >
          {mutation.isPending ? "Saving…" : saved ? "Saved ✓" : "Save"}
        </button>
      </div>
    </form>
  );
}
