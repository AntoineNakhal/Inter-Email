import { useState, useEffect } from "react";
import type { ThreadAnalysis, ThreadOverride, ThreadOverrideRequest } from "../../types/api";

const CATEGORIES = [
  "Urgent / Executive",
  "Customer / Partner",
  "Events / Logistics",
  "Finance / Admin",
  "FYI / Low Priority",
  "Classified / Sensitive",
];

const URGENCY_LEVELS = ["high", "medium", "low", "unknown"];

const RELEVANCE_BUCKETS = [
  { value: "must_review", label: "Must Review" },
  { value: "important", label: "Important" },
  { value: "maybe", label: "Maybe" },
  { value: "noise", label: "Noise" },
];

type TriBool = boolean | null; // null = "use AI value"

function TriToggle({
  label,
  value,
  aiValue,
  onChange,
}: {
  label: string;
  value: TriBool;
  aiValue?: boolean | null;
  onChange: (v: TriBool) => void;
}) {
  const aiLabel = aiValue === true ? "Yes (AI)" : aiValue === false ? "No (AI)" : "AI";
  return (
    <div className="override-row">
      <span className="override-row__label">{label}</span>
      <div className="override-tri-toggle">
        <button
          type="button"
          className={`override-tri-toggle__btn${value === true ? " override-tri-toggle__btn--on" : ""}`}
          onClick={() => onChange(value === true ? null : true)}
          title="Force ON"
        >
          Yes
        </button>
        <button
          type="button"
          className={`override-tri-toggle__btn${value === false ? " override-tri-toggle__btn--off" : ""}`}
          onClick={() => onChange(value === false ? null : false)}
          title="Force OFF"
        >
          No
        </button>
        <span
          className={`override-tri-toggle__auto${value === null ? " override-tri-toggle__auto--active" : ""}`}
          title="Use AI value"
        >
          {aiLabel}
        </span>
      </div>
    </div>
  );
}

interface OverrideModalProps {
  threadId: string;
  current: ThreadOverride | null;
  analysis?: ThreadAnalysis | null;
  disagreements?: Record<string, string>;
  onSave: (payload: ThreadOverrideRequest) => void;
  onClear: () => void;
  onClose: () => void;
  isSaving: boolean;
  isClearing: boolean;
}

export function OverrideModal({
  threadId: _threadId,
  current,
  analysis,
  disagreements = {},
  onSave,
  onClear,
  onClose,
  isSaving,
  isClearing,
}: OverrideModalProps) {
  const [category, setCategory] = useState<string | null>(current?.category ?? null);
  const [urgency, setUrgency] = useState<string | null>(current?.urgency ?? null);
  const [relevanceBucket, setRelevanceBucket] = useState<string | null>(current?.relevance_bucket ?? null);
  const [needsActionToday, setNeedsActionToday] = useState<TriBool>(current?.needs_action_today ?? null);
  const [waitingOnUs, setWaitingOnUs] = useState<TriBool>(current?.waiting_on_us ?? null);
  const [needsNextAction, setNeedsNextAction] = useState<TriBool>(current?.needs_next_action ?? null);
  const [shouldDraftReply, setShouldDraftReply] = useState<TriBool>(current?.should_draft_reply ?? null);
  const [notes, setNotes] = useState(current?.notes ?? "");

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  const hasDisagreements = Object.keys(disagreements).length > 0;

  function handleSave() {
    onSave({
      category,
      urgency,
      relevance_bucket: relevanceBucket,
      needs_action_today: needsActionToday,
      waiting_on_us: waitingOnUs,
      needs_next_action: needsNextAction,
      should_draft_reply: shouldDraftReply,
      notes,
    });
  }

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label="Thread overrides">
      <div className="modal override-modal" onClick={(e) => e.stopPropagation()}>

        <div className="modal__header">
          <h2 className="modal__title">Override AI Analysis</h2>
          <button className="modal__close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <p className="override-modal__hint">
          These corrections are passed to the AI as soft hints on the next re-analysis.
          The AI may still disagree — if so, both values are shown.
          Set a field to <strong>AI</strong> to let the AI decide freely.
        </p>

        {hasDisagreements && (
          <div className="override-modal__disagreements">
            <p className="override-modal__disagreements-title">⚠ AI disagreed with {Object.keys(disagreements).length} override{Object.keys(disagreements).length > 1 ? "s" : ""} last analysis</p>
            {Object.entries(disagreements).map(([field, reason]) => (
              <p key={field} className="override-modal__disagreements-item">
                <strong>{field}:</strong> {reason}
              </p>
            ))}
          </div>
        )}

        <div className="override-modal__body">

          {/* Dropdowns */}
          <div className="override-row">
            <label className="override-row__label" htmlFor="override-category">Category</label>
            <select
              id="override-category"
              className="override-select"
              value={category ?? ""}
              onChange={(e) => setCategory(e.target.value || null)}
            >
              <option value="">{analysis?.category ? `${analysis.category} (AI)` : "— AI decides —"}</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>

          <div className="override-row">
            <label className="override-row__label" htmlFor="override-urgency">Urgency</label>
            <select
              id="override-urgency"
              className="override-select"
              value={urgency ?? ""}
              onChange={(e) => setUrgency(e.target.value || null)}
            >
              <option value="">{analysis?.urgency ? `${analysis.urgency} (AI)` : "— AI decides —"}</option>
              {URGENCY_LEVELS.map((u) => (
                <option key={u} value={u}>{u.charAt(0).toUpperCase() + u.slice(1)}</option>
              ))}
            </select>
          </div>

          <div className="override-row">
            <label className="override-row__label" htmlFor="override-relevance">Priority bucket</label>
            <select
              id="override-relevance"
              className="override-select"
              value={relevanceBucket ?? ""}
              onChange={(e) => setRelevanceBucket(e.target.value || null)}
            >
              <option value="">— AI decides —</option>
              {RELEVANCE_BUCKETS.map((b) => (
                <option key={b.value} value={b.value}>{b.label}</option>
              ))}
            </select>
          </div>

          <div className="override-modal__divider" />

          {/* Tri-state toggles — show actual AI value on the auto button */}
          <TriToggle label="Needs action today" value={needsActionToday} aiValue={analysis?.needs_action_today} onChange={setNeedsActionToday} />
          <TriToggle label="Waiting on us" value={waitingOnUs} aiValue={analysis?.waiting_on_us ?? null} onChange={setWaitingOnUs} />
          <TriToggle label="Needs next action" value={needsNextAction} aiValue={analysis?.needs_next_action} onChange={setNeedsNextAction} />
          <TriToggle label="Should draft reply" value={shouldDraftReply} aiValue={analysis?.should_draft_reply} onChange={setShouldDraftReply} />

          <div className="override-modal__divider" />

          {/* Notes */}
          <div className="override-row override-row--col">
            <label className="override-row__label" htmlFor="override-notes">Notes (optional)</label>
            <textarea
              id="override-notes"
              className="override-textarea"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Why did you override this? Helps the AI learn your preferences."
            />
          </div>
        </div>

        <div className="modal__footer">
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={onClear}
            disabled={isClearing || isSaving}
          >
            {isClearing ? "Clearing…" : "Clear overrides"}
          </button>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn--primary btn--sm"
              onClick={handleSave}
              disabled={isSaving || isClearing}
            >
              {isSaving ? "Saving…" : "Save overrides"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
