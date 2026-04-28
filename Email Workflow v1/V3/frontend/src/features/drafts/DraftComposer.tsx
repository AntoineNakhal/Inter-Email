import { useRef, useState, useEffect, type DragEvent } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faCalendarDays,
  faPaperclip,
  faPen,
  faXmark,
  faPaperPlane,
  faBolt,
  faTriangleExclamation,
  faArrowRight,
  faArrowLeft,
} from "@fortawesome/free-solid-svg-icons";

import { useDraftMutation } from "../../hooks/useApi";
import type { EmailThread } from "../../types/api";

type Props = { thread: EmailThread; recommended?: boolean };

const STAGES = ["date", "attachments", "instructions"] as const;
type Stage = (typeof STAGES)[number];

export function DraftComposer({ thread, recommended = false }: Props) {
  const mutation = useDraftMutation(thread.thread_id);
  const [isOpen, setIsOpen] = useState(false);
  const [currentStage, setCurrentStage] = useState(0);
  const [confirmSkip, setConfirmSkip] = useState(false);

  const [selectedDay, setSelectedDay] = useState("");
  const [selectedTime, setSelectedTime] = useState("");
  const selectedDate = selectedDay ? (selectedTime ? `${selectedDay}T${selectedTime}` : selectedDay) : "";
  const [files, setFiles] = useState<File[]>([]);
  const [instructions, setInstructions] = useState("");
  const [isDraggingOver, setIsDraggingOver] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const draft = mutation.data ?? thread.latest_draft;
  const analysis = thread.analysis;

  const stageConfig: Record<Stage, {
    label: string;
    icon: typeof faCalendarDays;
    recommended: boolean;
    reason: string | null;
    hasValue: boolean;
  }> = {
    date: {
      label: "Date",
      icon: faCalendarDays,
      recommended: Boolean(analysis?.draft_needs_date),
      reason: analysis?.draft_date_reason ?? null,
      hasValue: selectedDay.trim().length > 0,
    },
    attachments: {
      label: "Attachments",
      icon: faPaperclip,
      recommended: Boolean(analysis?.draft_needs_attachment),
      reason: analysis?.draft_attachment_reason ?? null,
      hasValue: files.length > 0,
    },
    instructions: {
      label: "Instructions",
      icon: faPen,
      recommended: false,
      reason: null,
      hasValue: instructions.trim().length > 0,
    },
  };

  const isLast = currentStage === STAGES.length - 1;
  const stage = STAGES[currentStage];
  const config = stageConfig[stage];

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen]);

  function open() {
    setCurrentStage(0);
    setConfirmSkip(false);
    mutation.reset();
    setIsOpen(true);
  }

  function close() {
    setIsOpen(false);
    setConfirmSkip(false);
  }

  function tryAdvance() {
    if (config.recommended && !config.hasValue) {
      setConfirmSkip(true);
      return;
    }
    advance();
  }

  function advance() {
    setConfirmSkip(false);
    if (isLast) {
      generate();
    } else {
      setCurrentStage((s) => s + 1);
    }
  }

  function generate() {
    mutation.mutate({
      selected_date: selectedDate || null,
      attachment_names: files.map((f) => f.name),
      user_instructions: instructions,
    });
  }

  function mergeFiles(incoming: File[]) {
    setFiles((curr) => {
      const seen = new Set(curr.map((f) => f.name));
      return [...curr, ...incoming.filter((f) => !seen.has(f.name))];
    });
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDraggingOver(false);
    if (e.dataTransfer.files?.length) mergeFiles(Array.from(e.dataTransfer.files));
  }

  return (
    <>
      <button
        className={`button ${recommended ? "" : "button--ghost"} draft-trigger`}
        type="button"
        onClick={open}
      >
        <FontAwesomeIcon icon={faBolt} />
        {recommended ? "Draft Reply" : "Make Draft"}
      </button>

      {isOpen && (
        <div className="draft-modal-overlay" onClick={close}>
          <div className="draft-modal" onClick={(e) => e.stopPropagation()}>

            <div className="draft-modal__header">
              <div>
                <p className="eyebrow">Draft Reply</p>
                <h3>Compose with AI</h3>
              </div>
              <button className="draft-modal__close" onClick={close} aria-label="Close">
                <FontAwesomeIcon icon={faXmark} />
              </button>
            </div>

            {/* Step indicator */}
            <div className="draft-steps">
              {STAGES.map((s, i) => {
                const c = stageConfig[s];
                const isActive = i === currentStage;
                const isDone = i < currentStage;
                return (
                  <div
                    key={s}
                    className={`draft-step ${isActive ? "draft-step--active" : ""} ${isDone ? "draft-step--done" : ""}`}
                  >
                    <div className="draft-step__dot">
                      <FontAwesomeIcon icon={c.icon} />
                    </div>
                    <span className="draft-step__label">{c.label}</span>
                    {c.recommended && (
                      <span className="draft-step__badge">Recommended</span>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Stage content */}
            <div className="draft-stage-body">
              <div className="draft-stage-body__status">
                {config.recommended ? (
                  <span className="pill tone-watch">Recommended by AI</span>
                ) : (
                  <span className="pill tone-neutral">Optional</span>
                )}
              </div>

              {stage === "date" && (
                <>
                  <p className="draft-stage-body__hint">
                    {config.recommended && config.reason
                      ? config.reason
                      : "If your reply references a specific date or time, add it here so the AI can include it naturally."}
                  </p>
                  <div className="draft-date-row">
                    <label className="draft-date-field">
                      <span className="draft-date-field__label">Day</span>
                      <input
                        type="date"
                        value={selectedDay}
                        onChange={(e) => setSelectedDay(e.target.value)}
                      />
                    </label>
                    <label className="draft-date-field">
                      <span className="draft-date-field__label">Time</span>
                      <input
                        type="time"
                        value={selectedTime}
                        onChange={(e) => setSelectedTime(e.target.value)}
                        disabled={!selectedDay}
                      />
                    </label>
                  </div>
                  {selectedDay && (
                    <button
                      className="button button--ghost"
                      type="button"
                      style={{ alignSelf: "flex-start", fontSize: "0.78rem" }}
                      onClick={() => { setSelectedDay(""); setSelectedTime(""); }}
                    >
                      Clear
                    </button>
                  )}
                </>
              )}

              {stage === "attachments" && (
                <>
                  <p className="draft-stage-body__hint">
                    {config.recommended && config.reason
                      ? config.reason
                      : "Drop any files you plan to attach. Their filenames are sent to the AI as context — no file content is uploaded."}
                  </p>
                  <div
                    className={`draft-stage__drop${isDraggingOver ? " draft-stage__drop--over" : ""}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => fileInputRef.current?.click()}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        fileInputRef.current?.click();
                      }
                    }}
                    onDrop={handleDrop}
                    onDragOver={(e) => { e.preventDefault(); setIsDraggingOver(true); }}
                    onDragLeave={() => setIsDraggingOver(false)}
                    aria-label="Drop files or click to pick"
                  >
                    <span className="draft-stage__drop-icon">⇪</span>
                    <span>{isDraggingOver ? "Release to add" : "Drop files here or click to pick"}</span>
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    style={{ display: "none" }}
                    onChange={(e) => {
                      if (e.target.files?.length) {
                        mergeFiles(Array.from(e.target.files));
                        e.target.value = "";
                      }
                    }}
                  />
                  {files.length ? (
                    <ul className="draft-stage__files">
                      {files.map((f) => (
                        <li key={f.name}>
                          <span>{f.name}</span>
                          <button
                            type="button"
                            onClick={() => setFiles((c) => c.filter((x) => x.name !== f.name))}
                            aria-label={`Remove ${f.name}`}
                          >
                            ×
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </>
              )}

              {stage === "instructions" && (
                <>
                  <p className="draft-stage-body__hint">
                    Any extra guidance for the AI — tone, length, specific points to include or avoid.
                  </p>
                  <textarea
                    rows={5}
                    value={instructions}
                    onChange={(e) => setInstructions(e.target.value)}
                    placeholder="e.g. Keep it under 3 sentences. Confirm the Tuesday meeting."
                  />
                </>
              )}

              {/* Skip confirmation */}
              {confirmSkip && (
                <div className="draft-skip-warning">
                  <FontAwesomeIcon icon={faTriangleExclamation} className="draft-skip-warning__icon" />
                  <div>
                    <p className="draft-skip-warning__title">AI recommends including this</p>
                    <p className="draft-skip-warning__body">
                      {config.reason ?? "The AI flagged this stage as important for a good draft."}
                      {" "}Are you sure you want to continue without it?
                    </p>
                    <div className="draft-skip-warning__actions">
                      <button
                        className="button button--ghost"
                        type="button"
                        onClick={() => setConfirmSkip(false)}
                      >
                        Go back
                      </button>
                      <button className="button" type="button" onClick={advance}>
                        Continue without
                      </button>
                    </div>
                  </div>
                </div>
              )}

            </div>

            {/* Navigation */}
            {!confirmSkip && (
              <div className="draft-modal__nav">
                <button
                  className="button button--ghost"
                  type="button"
                  disabled={currentStage === 0}
                  onClick={() => { setConfirmSkip(false); setCurrentStage((s) => s - 1); }}
                >
                  <FontAwesomeIcon icon={faArrowLeft} />
                  Back
                </button>

                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button
                    className="button"
                    type="button"
                    onClick={isLast ? advance : tryAdvance}
                    disabled={isLast && mutation.isPending}
                  >
                    {isLast ? (
                      <>
                        <FontAwesomeIcon icon={faBolt} />
                        {mutation.isPending ? "Generating…" : "Generate"}
                      </>
                    ) : (
                      <>
                        Next
                        <FontAwesomeIcon icon={faArrowRight} />
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}

            {/* Draft result */}
            {draft ? (
              <div className="draft-result">
                <div className="draft-result__header">
                  <p className="eyebrow">Generated draft</p>
                  <button className="button draft-result__send" type="button" disabled>
                    <FontAwesomeIcon icon={faPaperPlane} />
                    Send
                  </button>
                </div>
                <p className="draft-result__subject">{draft.subject}</p>
                <pre className="draft-result__body">{draft.body}</pre>
              </div>
            ) : null}

          </div>
        </div>
      )}
    </>
  );
}
