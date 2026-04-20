import { useLocation } from "react-router-dom";

import { useGmailConnectionStatus, useSettings } from "../hooks/useApi";

export function SettingsPage() {
  const location = useLocation();
  const { data, isLoading, error } = useSettings();
  const {
    data: gmailStatus,
    isLoading: gmailLoading,
    error: gmailError,
  } = useGmailConnectionStatus();
  const searchParams = new URLSearchParams(location.search);
  const gmailResult = searchParams.get("gmail");
  const gmailMessage = searchParams.get("message");

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
              <li>Default: {data.ai_default_provider}</li>
              <li>Thread analysis: {data.thread_analysis_provider}</li>
              <li>Queue summary: {data.queue_summary_provider}</li>
              <li>Drafts: {data.draft_provider}</li>
              <li>CRM: {data.crm_provider}</li>
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
        </div>
      ) : null}
    </section>
  );
}
