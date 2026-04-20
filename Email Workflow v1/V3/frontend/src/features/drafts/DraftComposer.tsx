import { useState } from "react";

import { useDraftMutation } from "../../hooks/useApi";
import type { EmailThread } from "../../types/api";

type DraftComposerProps = {
  thread: EmailThread;
};

export function DraftComposer({ thread }: DraftComposerProps) {
  const mutation = useDraftMutation(thread.thread_id);
  const [selectedDate, setSelectedDate] = useState("");
  const [attachments, setAttachments] = useState("");
  const [instructions, setInstructions] = useState("");
  const draft = mutation.data ?? thread.latest_draft;

  return (
    <section className="panel stack draft-composer">
      <div className="thread-detail__section-head">
        <p className="eyebrow">Draft Workflow</p>
        <h3>Generate Reply</h3>
      </div>

      <label className="draft-composer__field">
        Proposed date
        <input
          type="text"
          value={selectedDate}
          onChange={(event) => setSelectedDate(event.target.value)}
          placeholder="April 21 at 2:00 PM"
        />
      </label>

      <label className="draft-composer__field">
        Attachments
        <input
          type="text"
          value={attachments}
          onChange={(event) => setAttachments(event.target.value)}
          placeholder="proposal.pdf, schedule.docx"
        />
      </label>

      <label className="draft-composer__field">
        Extra instructions
        <textarea
          rows={4}
          value={instructions}
          onChange={(event) => setInstructions(event.target.value)}
          placeholder="Tone, constraints, or context for the reply."
        />
      </label>

      <button
        className="button"
        onClick={() =>
          mutation.mutate({
            selected_date: selectedDate || null,
            attachment_names: attachments
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean),
            user_instructions: instructions,
          })
        }
        disabled={mutation.isPending}
      >
        {mutation.isPending ? "Generating..." : "Generate Draft"}
      </button>

      {draft ? (
        <div className="draft-preview">
          <p className="eyebrow">Latest Draft</p>
          <h4 className="draft-preview__subject">{draft.subject}</h4>
          <pre>{draft.body}</pre>
        </div>
      ) : null}
    </section>
  );
}
