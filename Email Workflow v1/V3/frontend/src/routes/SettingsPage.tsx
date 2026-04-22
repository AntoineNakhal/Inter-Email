import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

import {
  useGmailConnectionStatus,
  useSettings,
  useUpdateSettingsMutation,
} from "../hooks/useApi";
import type { RuntimeSettingsUpdate } from "../types/api";

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
  const [formState, setFormState] = useState<RuntimeSettingsUpdate>({
    ai_mode: "openai",
    local_ai_force_all_threads: false,
    local_ai_model: "",
    local_ai_agent_prompt: "",
  });

  useEffect(() => {
    if (!data) {
      return;
    }
    setFormState({
      ai_mode: data.ai_mode,
      local_ai_force_all_threads: data.local_ai_force_all_threads,
      local_ai_model: data.local_ai_model,
      local_ai_agent_prompt: data.local_ai_agent_prompt,
    });
  }, [data]);

  return (
    <section className="page stack">
      <div className="hero hero--compact">
        <div>
          <p className="eyebrow">Deployment Settings</p>
          <h1>Runtime Configuration</h1>
        </div>
      </div>

      {isLoading ? <p>Loading settings...</p> : null}
      {error instanceof Error ? <p>{error.message}</p> : null}
      {gmailLoading ? <p>Checking Gmail connection...</p> : null}
      {gmailError instanceof Error ? <p>{gmailError.message}</p> : null}
      {updateSettingsMutation.isSuccess ? (
        <div className="panel panel--summary">
          <p className="eyebrow">AI Runtime</p>
          <p className="summary-text">
            AI runtime settings saved. The next inbox refresh will use the new mode.
          </p>
        </div>
      ) : null}
      {updateSettingsMutation.error instanceof Error ? (
        <div className="panel">
          <p className="eyebrow">AI Runtime</p>
          <p>{updateSettingsMutation.error.message}</p>
        </div>
      ) : null}
      {gmailResult === "connected" ? (
        <div className="panel panel--summary">
          <p className="eyebrow">Gmail</p>
          <p className="summary-text">
            Gmail authorization completed. The app can now use your connected mailbox.
          </p>
        </div>
      ) : null}
      {gmailResult === "error" ? (
        <div className="panel">
          <p className="eyebrow">Gmail</p>
          <p>{gmailMessage ?? "The Gmail connection flow failed."}</p>
        </div>
      ) : null}

      {data ? (
        <div className="settings-grid">
          <div className="panel">
            <p className="eyebrow">Environment</p>
            <h3>{data.environment}</h3>
            <p>{data.database_url}</p>
          </div>

          <div className="panel">
            <p className="eyebrow">AI Routing</p>
            <ul className="stack stack--tight">
              <li>Configured default: {data.ai_default_provider}</li>
              <li>Thread analysis: {data.thread_analysis_provider}</li>
              <li>Queue summary: {data.queue_summary_provider}</li>
              <li>Drafts: {data.draft_provider}</li>
              <li>CRM: {data.crm_provider}</li>
              <li>Active mode: {data.ai_mode === "local" ? "Local AI" : "OpenAI"}</li>
            </ul>
          </div>

          <div className="panel">
            <p className="eyebrow">Gmail Connection</p>
            <h3>
              {gmailStatus?.connected
                ? gmailStatus.email_address ?? "Connected"
                : "Not connected"}
            </h3>
            <p>
              {gmailStatus?.connected
                ? "Gmail is ready for sync."
                : gmailStatus?.error_message ??
                  "Connect a Gmail account to enable inbox sync."}
            </p>
            <p className="settings-path">
              Credentials: {gmailStatus?.credentials_path ?? "unknown"}
            </p>
            <p className="settings-path">
              Token: {gmailStatus?.token_path ?? "unknown"}
            </p>
            {gmailStatus?.connect_url && gmailStatus.credentials_configured ? (
              <a className="button" href={gmailStatus.connect_url}>
                {gmailStatus.connected ? "Reconnect Gmail" : "Connect Gmail"}
              </a>
            ) : null}
          </div>

          <form
            className="panel settings-form"
            onSubmit={(event) => {
              event.preventDefault();
              updateSettingsMutation.mutate(formState);
            }}
          >
            <p className="eyebrow">Local AI</p>
            <h3>Provider mode</h3>
            <label className="settings-form__field">
              <span>AI mode</span>
              <select
                value={formState.ai_mode}
                onChange={(event) =>
                  setFormState((current) => ({
                    ...current,
                    ai_mode: event.target.value,
                    local_ai_force_all_threads:
                      event.target.value === "local"
                        ? true
                        : current.local_ai_force_all_threads,
                  }))
                }
              >
                <option value="openai">OpenAI</option>
                <option value="local">Local AI (Ollama)</option>
              </select>
            </label>

            <label className="settings-form__checkbox">
              <input
                type="checkbox"
                checked={formState.local_ai_force_all_threads}
                onChange={(event) =>
                  setFormState((current) => ({
                    ...current,
                    local_ai_force_all_threads: event.target.checked,
                  }))
                }
              />
              <span>
                When Local AI is active, analyze every fetched email thread and skip
                the usual triage gate.
              </span>
            </label>

            <label className="settings-form__field">
              <span>Ollama base URL</span>
              <input type="text" value={data.ollama_base_url} readOnly />
            </label>
            <p className="summary-text">
              If the API runs in Docker while Ollama runs on your machine, the base
              URL usually needs to be `http://host.docker.internal:11434` in your
              `.env`.
            </p>

            <label className="settings-form__field">
              <span>Local model name</span>
              <input
                type="text"
                value={formState.local_ai_model}
                onChange={(event) =>
                  setFormState((current) => ({
                    ...current,
                    local_ai_model: event.target.value,
                  }))
                }
                placeholder={data.ollama_model_thread_analysis || "llama3.1:8b"}
              />
            </label>

            <label className="settings-form__field">
              <span>Your local agent prompt</span>
              <textarea
                rows={8}
                value={formState.local_ai_agent_prompt}
                onChange={(event) =>
                  setFormState((current) => ({
                    ...current,
                    local_ai_agent_prompt: event.target.value,
                  }))
                }
                placeholder="Example: You are my internal email operations agent. Be strict, concise, and always produce a clear next action."
              />
            </label>

            <p className="summary-text">
              Local AI mode routes thread analysis, queue summary, drafts, and CRM
              extraction through Ollama. Your custom agent prompt is appended to the
              local provider instructions.
            </p>

            <button className="button" disabled={updateSettingsMutation.isPending}>
              {updateSettingsMutation.isPending ? "Saving..." : "Save AI settings"}
            </button>
          </form>
        </div>
      ) : null}
    </section>
  );
}
