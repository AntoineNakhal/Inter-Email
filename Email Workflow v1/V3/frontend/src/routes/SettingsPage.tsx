import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import {
  useGmailConnectionStatus,
  useSettings,
  useUpdateSettingsMutation,
} from "../hooks/useApi";
import type { RuntimeSettingsUpdate, SettingsSummary } from "../types/api";

const SETTINGS_DRAFT_KEY = "inter-op.v3.settings-draft";
const SAVE_DEBOUNCE_MS = 700;

type SaveState = "idle" | "saving" | "saved" | "error";

function toFormState(settings: SettingsSummary): RuntimeSettingsUpdate {
  return {
    ai_mode: settings.ai_mode,
    local_ai_force_all_threads: settings.local_ai_force_all_threads,
    local_ai_model: settings.local_ai_model,
    local_ai_agent_prompt: settings.local_ai_agent_prompt,
  };
}

function serializeFormState(settings: RuntimeSettingsUpdate): string {
  return JSON.stringify({
    ai_mode: settings.ai_mode,
    local_ai_force_all_threads: Boolean(settings.local_ai_force_all_threads),
    local_ai_model: settings.local_ai_model,
    local_ai_agent_prompt: settings.local_ai_agent_prompt,
  });
}

function loadStoredDraft(): RuntimeSettingsUpdate | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.localStorage.getItem(SETTINGS_DRAFT_KEY);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<RuntimeSettingsUpdate>;
    // Coerce legacy / unknown values back to a known mode. "claude" was
    // added when we wired up the Anthropic provider; older drafts that
    // pre-date it just round-trip safely.
    const incomingMode = parsed.ai_mode;
    const safeMode: RuntimeSettingsUpdate["ai_mode"] =
      incomingMode === "local" || incomingMode === "claude" ? incomingMode : "openai";
    return {
      ai_mode: safeMode,
      local_ai_force_all_threads: Boolean(parsed.local_ai_force_all_threads),
      local_ai_model: String(parsed.local_ai_model ?? ""),
      local_ai_agent_prompt: String(parsed.local_ai_agent_prompt ?? ""),
    };
  } catch {
    window.localStorage.removeItem(SETTINGS_DRAFT_KEY);
    return null;
  }
}

function storeDraft(settings: RuntimeSettingsUpdate): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(SETTINGS_DRAFT_KEY, JSON.stringify(settings));
}

function clearStoredDraft(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(SETTINGS_DRAFT_KEY);
}

/**
 * Returns the *effective* per-task routing taking the current AI mode into
 * account. The mode toggles in `RuntimeSettings.ai_mode` short-circuit the
 * env-var-based provider config: when "local" or "claude" is active,
 * AIProviderRouter routes ALL tasks to that single provider regardless of
 * what AI_*_PROVIDER env vars say. Without this helper, the Technical
 * details panel would show "Analysis openai, queue openai..." even while
 * the backend is actually using Ollama or Anthropic — that was the lie.
 */
function effectiveRouting(
  settings: SettingsSummary,
  mode: string,
): {
  thread_analysis: string;
  queue: string;
  draft: string;
  crm: string;
} {
  if (mode === "local") {
    return {
      thread_analysis: "ollama",
      queue: "ollama",
      draft: "ollama",
      crm: "ollama",
    };
  }
  if (mode === "claude") {
    return {
      thread_analysis: "anthropic",
      queue: "anthropic",
      draft: "anthropic",
      crm: "anthropic",
    };
  }
  return {
    thread_analysis: settings.thread_analysis_provider,
    queue: settings.queue_summary_provider,
    draft: settings.draft_provider,
    crm: settings.crm_provider,
  };
}

function formatSavedAt(savedAt: string | null): string | null {
  if (!savedAt) {
    return null;
  }

  const date = new Date(savedAt);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

// Order matters: it drives the active-index lookup for the animated
// selector indicator below.
const AI_MODE_ORDER: ReadonlyArray<RuntimeSettingsUpdate["ai_mode"]> = [
  "openai",
  "claude",
  "local",
];

export function SettingsPage() {
  const location = useLocation();
  const { data, isLoading, error } = useSettings();
  const updateSettingsMutation = useUpdateSettingsMutation();
  const {
    data: gmailStatus,
    isLoading: gmailLoading,
    error: gmailError,
  } = useGmailConnectionStatus();
  const searchParams = new URLSearchParams(location.search);
  const gmailResult = searchParams.get("gmail");
  const gmailMessage = searchParams.get("message");
  const [formState, setFormState] = useState<RuntimeSettingsUpdate | null>(null);
  const [savedSnapshot, setSavedSnapshot] = useState<RuntimeSettingsUpdate | null>(
    null,
  );
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const [restoredDraft, setRestoredDraft] = useState(false);
  const didHydrateRef = useRef(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Animated selector for the AI mode toggle. We measure the active
  // button's full bounding box (offsetLeft/Top/Width/Height) and slide
  // a single indicator div between them. This avoids hardcoding button
  // widths so the animation is robust to font size, padding, locale, etc.
  //
  // `firstMeasurementDoneRef` tracks the very first measurement so we can
  // suppress the CSS transition on initial render — otherwise the
  // indicator would visibly slide from (0,0) to its target position
  // every time the page mounts (e.g. on hard refresh).
  const aiModeButtonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const aiModeFirstMeasurementDoneRef = useRef(false);
  const [aiModeIndicator, setAiModeIndicator] = useState<{
    left: number;
    top: number;
    width: number;
    height: number;
    ready: boolean;
    animate: boolean;
  }>({ left: 0, top: 0, width: 0, height: 0, ready: false, animate: false });

  useEffect(() => {
    if (!data || didHydrateRef.current) {
      return;
    }

    const serverState = toFormState(data);
    const storedDraft = loadStoredDraft();
    const nextState = storedDraft ?? serverState;
    const matchesServer =
      serializeFormState(nextState) === serializeFormState(serverState);

    setFormState(nextState);
    setSavedSnapshot(serverState);
    setLastSavedAt(data.runtime_settings_updated_at);
    setRestoredDraft(Boolean(storedDraft) && !matchesServer);
    setSaveState(matchesServer ? "saved" : "idle");
    setSaveError(null);

    if (matchesServer) {
      clearStoredDraft();
    }

    didHydrateRef.current = true;
  }, [data]);

  // Re-measure the active AI-mode button's bounding box whenever the
  // mode changes, the form state arrives, or the window resizes.
  //
  // useLayoutEffect (vs useEffect) so the measurement happens before
  // browser paint — avoids a one-frame flash of the indicator at the
  // wrong position on first render.
  //
  // `animate=false` is forced on the very first measurement so the
  // initial position lands instantly. After that we re-enable transitions
  // (via requestAnimationFrame so the no-transition position commits to
  // the DOM first) so subsequent mode changes glide.
  useLayoutEffect(() => {
    if (!formState) return;
    const activeIndex = AI_MODE_ORDER.indexOf(formState.ai_mode);
    function measure() {
      if (activeIndex < 0) return;
      const target = aiModeButtonRefs.current[activeIndex];
      if (!target) return;
      const isFirst = !aiModeFirstMeasurementDoneRef.current;
      setAiModeIndicator({
        left: target.offsetLeft,
        top: target.offsetTop,
        width: target.offsetWidth,
        height: target.offsetHeight,
        ready: true,
        animate: !isFirst,
      });
      if (isFirst) {
        aiModeFirstMeasurementDoneRef.current = true;
        // After the no-transition initial position is painted, enable
        // animation for future moves.
        requestAnimationFrame(() => {
          setAiModeIndicator((current) => ({ ...current, animate: true }));
        });
      }
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [formState?.ai_mode, formState]);

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
      }
    };
  }, []);

  const localFallbackModel = data?.ollama_model_thread_analysis?.trim() ?? "";
  const localModelConfigured = Boolean(
    formState?.local_ai_model.trim() || localFallbackModel,
  );
  const localModeNeedsModel = Boolean(
    formState?.ai_mode === "local" && !localModelConfigured,
  );
  const hasUnsavedChanges = Boolean(
    formState &&
      savedSnapshot &&
      serializeFormState(formState) !== serializeFormState(savedSnapshot),
  );
  const showingLocalSetup = Boolean(
    formState?.ai_mode === "local" ||
      formState?.local_ai_model.trim() ||
      formState?.local_ai_agent_prompt.trim(),
  );

  const submitSettings = (nextState: RuntimeSettingsUpdate) => {
    if (localModeNeedsModel) {
      return;
    }

    setSaveState("saving");
    setSaveError(null);
    updateSettingsMutation.mutate(
      {
        ...nextState,
        local_ai_force_all_threads: nextState.ai_mode === "local",
      },
      {
        onSuccess: (response) => {
          const nextSavedState = toFormState(response);
          setSavedSnapshot(nextSavedState);
          setFormState(nextSavedState);
          setLastSavedAt(response.runtime_settings_updated_at);
          setRestoredDraft(false);
          setSaveError(null);
          setSaveState("saved");
          clearStoredDraft();
        },
        onError: (mutationError) => {
          setSaveState("error");
          setSaveError(
            mutationError instanceof Error
              ? mutationError.message
              : "Settings could not be saved.",
          );
        },
      },
    );
  };

  useEffect(() => {
    if (!formState || !savedSnapshot) {
      return;
    }

    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }

    const serializedCurrent = serializeFormState(formState);
    const serializedSaved = serializeFormState(savedSnapshot);

    if (serializedCurrent === serializedSaved) {
      clearStoredDraft();
      if (saveState !== "saving") {
        setSaveState("saved");
      }
      return;
    }

    storeDraft(formState);
    setSaveError(null);
    setSaveState("idle");

    if (localModeNeedsModel) {
      return;
    }

    saveTimerRef.current = setTimeout(() => {
      submitSettings(formState);
    }, SAVE_DEBOUNCE_MS);

    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
      }
    };
  }, [formState, localModeNeedsModel, savedSnapshot]);

  const saveStatus = useMemo(() => {
    if (saveState === "error") {
      return {
        pillClass: "tone-urgent",
        title: "Save failed",
        detail: saveError ?? "We couldn't save your settings.",
      };
    }

    if (localModeNeedsModel) {
      return {
        pillClass: "tone-watch",
        title: "Need a model",
        detail: "Add an Ollama model name before switching to Local AI.",
      };
    }

    if (saveState === "saving") {
      return {
        pillClass: "tone-watch",
        title: "Saving",
        detail: "Your changes are being saved automatically.",
      };
    }

    if (hasUnsavedChanges) {
      return {
        pillClass: "tone-neutral",
        title: "Changes pending",
        detail: "Hold on for a second while the save runs.",
      };
    }

    if (restoredDraft) {
      return {
        pillClass: "tone-neutral",
        title: "Draft restored",
        detail: "Your last settings draft was brought back after refresh.",
      };
    }

    const savedAtLabel = formatSavedAt(lastSavedAt);
    return {
      pillClass: "tone-positive",
      title: "Saved",
      detail: savedAtLabel ? `Last saved ${savedAtLabel}.` : "Everything is up to date.",
    };
  }, [
    hasUnsavedChanges,
    lastSavedAt,
    localModeNeedsModel,
    restoredDraft,
    saveError,
    saveState,
  ]);

  const activeModeLabel =
    formState?.ai_mode === "local"
      ? "Local AI"
      : formState?.ai_mode === "claude"
        ? "Claude"
        : "OpenAI";
  const gmailSummary = gmailStatus?.connected
    ? "This is the mailbox the app will sync and analyze."
    : gmailStatus?.credentials_configured
      ? "Connect a mailbox to start syncing."
      : "Add your Gmail OAuth credentials to enable the connection.";

  return (
    <section className="page stack">
      <div className="hero hero--compact settings-hero">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>Workspace settings</h1>
          <p className="summary-text">
            Connect Gmail, choose your AI mode, and the rest saves automatically.
          </p>
        </div>

        <div className="settings-status">
          <span className={`pill ${saveStatus.pillClass}`}>{saveStatus.title}</span>
          <p className="settings-status__detail">{saveStatus.detail}</p>
        </div>
      </div>

      {/*
        Loading + transient error chatter intentionally removed. The
        page renders nothing until `data` is ready (the actual settings
        grid is gated on `data && formState`), so the user sees the
        finished UI instead of "Loading settings..." then "Checking
        Gmail..." flashing in succession. Real errors still surface via
        the save-error banner below and the saveStatus pill in the hero.
      */}

      {gmailResult === "connected" ? (
        <div className="panel panel--summary settings-banner">
          <p className="eyebrow">Gmail</p>
          <p className="summary-text">Gmail connection updated successfully.</p>
        </div>
      ) : null}

      {gmailResult === "error" ? (
        <div className="panel settings-banner settings-banner--alert">
          <p className="eyebrow">Gmail</p>
          <p>{gmailMessage ?? "The Gmail connection flow failed."}</p>
        </div>
      ) : null}

      {saveState === "error" ? (
        <div className="panel settings-banner settings-banner--alert">
          <div className="settings-panel__header">
            <div>
              <p className="eyebrow">Settings</p>
              <h3>Could not save</h3>
            </div>
            {formState ? (
              <button
                className="button button--ghost"
                type="button"
                onClick={() => submitSettings(formState)}
              >
                Retry save
              </button>
            ) : null}
          </div>
          <p>{saveError}</p>
        </div>
      ) : null}

      {data && formState ? (
        <div className="settings-grid settings-grid--settings">
          <section className="panel settings-panel">
            <div className="settings-panel__header">
              <div>
                <p className="eyebrow">Gmail</p>
                <h3>
                  {gmailStatus?.connected
                    ? gmailStatus.email_address ?? "Connected"
                    : "Not connected"}
                </h3>
              </div>
              <span
                className={`pill ${
                  gmailStatus?.connected ? "tone-positive" : "tone-watch"
                }`}
              >
                {gmailStatus?.connected ? "Connected" : "Needs connection"}
              </span>
            </div>

            <p className="summary-text">{gmailSummary}</p>

            {gmailStatus?.connect_url && gmailStatus.credentials_configured ? (
              <a className="button settings-button-row" href={gmailStatus.connect_url}>
                {gmailStatus.connected ? "Reconnect Gmail" : "Connect Gmail"}
              </a>
            ) : null}

            {(!gmailStatus?.connected && gmailStatus?.error_message) ||
            !gmailStatus?.credentials_configured ? (
              <details className="settings-tech settings-tech--inline">
                <summary>Connection details</summary>
                <div className="stack stack--tight">
                  {gmailStatus?.error_message ? <p>{gmailStatus.error_message}</p> : null}
                  <p className="settings-path">
                    Credentials: {gmailStatus?.credentials_path ?? "unknown"}
                  </p>
                  <p className="settings-path">
                    Token: {gmailStatus?.token_path ?? "unknown"}
                  </p>
                </div>
              </details>
            ) : null}
          </section>

          <section className="panel settings-panel">
            <div className="settings-panel__header">
              <div>
                <p className="eyebrow">AI mode</p>
                <h3>{activeModeLabel}</h3>
              </div>
              {/*
                Removed the redundant default-provider pill (it duplicated
                what the toggle below already conveys) and prevented it
                from making the header look noisy.
              */}
            </div>

            <div
              className="settings-toggle"
              role="tablist"
              aria-label="AI mode"
              style={{
                display: "flex",
                flexDirection: "row",
                gap: "8px",
                width: "100%",
                position: "relative",
              }}
            >
              {/*
                Animated active-state indicator. Slides between buttons
                on mode change. We position it absolutely behind the
                buttons (zIndex 0) and let the buttons render on top
                with transparent backgrounds (zIndex 1). The active
                button's text gets a contrasted color so it stays
                readable on top of the white slider.
              */}
              <span
                aria-hidden="true"
                style={{
                  position: "absolute",
                  left: aiModeIndicator.left,
                  top: aiModeIndicator.top,
                  width: aiModeIndicator.width,
                  height: aiModeIndicator.height,
                  background: "rgba(255, 255, 255, 0.95)",
                  borderRadius: "10px",
                  boxShadow: "0 2px 8px rgba(0, 0, 0, 0.18)",
                  // Transition is disabled on the very first measurement
                  // so the indicator lands at its initial position
                  // without a visible slide. From then on it glides.
                  transition: aiModeIndicator.animate
                    ? "left 280ms cubic-bezier(0.4, 0, 0.2, 1), top 280ms cubic-bezier(0.4, 0, 0.2, 1), width 280ms cubic-bezier(0.4, 0, 0.2, 1), height 280ms cubic-bezier(0.4, 0, 0.2, 1)"
                    : "none",
                  opacity: aiModeIndicator.ready ? 1 : 0,
                  pointerEvents: "none",
                  zIndex: 0,
                }}
              />

              {(
                [
                  { mode: "openai" as const, label: "OpenAI" },
                  { mode: "claude" as const, label: "Claude" },
                  { mode: "local" as const, label: "Local AI" },
                ]
              ).map((option, index) => {
                const isActive = formState.ai_mode === option.mode;
                return (
                  <button
                    key={option.mode}
                    ref={(element) => {
                      aiModeButtonRefs.current[index] = element;
                    }}
                    className="settings-toggle__button"
                    style={{
                      flex: 1,
                      position: "relative",
                      zIndex: 1,
                      background: "transparent",
                      border: "none",
                      cursor: "pointer",
                      padding: "10px 14px",
                      borderRadius: "10px",
                      color: isActive ? "#0b1020" : "inherit",
                      fontWeight: isActive ? 700 : 500,
                      transition: "color 200ms ease, font-weight 200ms ease",
                    }}
                    type="button"
                    onClick={() =>
                      setFormState((current) =>
                        current
                          ? {
                              ...current,
                              ai_mode: option.mode,
                              // local mode is the only one that flips the
                              // local-AI fan-out flag on; the other two
                              // explicitly clear it.
                              local_ai_force_all_threads: option.mode === "local",
                            }
                          : current,
                      )
                    }
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>

            <p className="summary-text">
              {/*
                Neutral, mode-agnostic copy so the card height stays
                constant when switching modes. The active provider is
                already visible from the toggle's selected button — no
                need to repeat it in prose.
              */}
              All workflow tasks (analysis, verification, drafts, queue summary, CRM) route through your selected provider.
            </p>

            {localModeNeedsModel ? (
              <p className="settings-alert">
                Add a local model name before switching fully to Local AI.
              </p>
            ) : null}
          </section>

          {/*
            The Local agent setup panel only makes sense when Local AI is the
            active mode. For OpenAI / Claude users it's just noise. Auto-save
            still triggers via the form-state effect, so hiding the form here
            doesn't break the save path — only the manual "Retry save"
            fallback is hidden, which is acceptable since the auto-save loop
            will re-fire on the next state change anyway.
          */}
          {formState.ai_mode === "local" ? (
            <form
              className="panel settings-form settings-panel settings-panel--wide"
              onSubmit={(event) => {
                event.preventDefault();
                submitSettings(formState);
              }}
            >
              <div className="settings-panel__header">
                <div>
                  <p className="eyebrow">Local agent</p>
                  <h3>{showingLocalSetup ? "Local AI setup" : "Prepare local AI"}</h3>
                </div>
                <span className="pill tone-positive">Active</span>
              </div>

              <label className="settings-form__field">
                <span>Model name</span>
                <input
                  aria-invalid={localModeNeedsModel}
                  type="text"
                  value={formState.local_ai_model}
                  onChange={(event) =>
                    setFormState((current) =>
                      current
                        ? {
                            ...current,
                            local_ai_model: event.target.value,
                          }
                        : current,
                    )
                  }
                  placeholder={localFallbackModel || "llama3.1:8b"}
                />
              </label>

              <label className="settings-form__field">
                <span>Agent instructions</span>
                <textarea
                  rows={6}
                  value={formState.local_ai_agent_prompt}
                  onChange={(event) =>
                    setFormState((current) =>
                      current
                        ? {
                            ...current,
                            local_ai_agent_prompt: event.target.value,
                          }
                        : current,
                    )
                  }
                  placeholder="You are my email workflow agent. Be concise, identify urgency, and always return a concrete next action."
                />
              </label>

              <div className="settings-support">
                <p className="summary-text">
                  Local mode uses your Ollama agents for thread analysis, verification, queueing, drafts, and CRM extraction.
                </p>

                {saveState === "error" ? (
                  <button className="button button--ghost" type="submit">
                    Retry save
                  </button>
                ) : null}
              </div>
            </form>
          ) : null}

          <details className="panel settings-tech settings-panel settings-panel--wide">
            <summary>Technical details</summary>
            <div className="settings-tech__grid">
              <div>
                <p className="settings-tech__label">Environment</p>
                <p>{data.environment}</p>
              </div>
              <div>
                <p className="settings-tech__label">Database</p>
                <p className="settings-path">{data.database_url}</p>
              </div>
              <div>
                <p className="settings-tech__label">Effective routing</p>
                {/*
                  Reflects what the AIProviderRouter will actually do once
                  the current settings save — NOT just the env-var
                  defaults, because mode "local" / "claude" override them.
                */}
                <p>
                  {(() => {
                    const routing = effectiveRouting(data, formState.ai_mode);
                    return `Analysis ${routing.thread_analysis}, queue ${routing.queue}, drafts ${routing.draft}, CRM ${routing.crm}`;
                  })()}
                </p>
              </div>
              <div>
                <p className="settings-tech__label">Ollama base URL</p>
                <p className="settings-path">{data.ollama_base_url}</p>
              </div>
            </div>
          </details>
        </div>
      ) : null}
    </section>
  );
}
