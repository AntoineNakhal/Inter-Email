/**
 * ConnectedAccounts — lists connected email accounts and lets the user add new ones.
 *
 * Placed in its own feature folder so it stays self-contained and easy to extend.
 * The parent (SettingsPage) just renders <ConnectedAccounts />.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

const API = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// ------------------------------------------------------------------ //
// Types                                                                 //
// ------------------------------------------------------------------ //

interface EmailAccount {
  id: number;
  provider: "gmail" | "outlook" | "icloud" | "imap";
  email_address: string;
  display_name: string | null;
  is_active: boolean;
}

// ------------------------------------------------------------------ //
// API helpers                                                           //
// ------------------------------------------------------------------ //

async function fetchAccounts(): Promise<EmailAccount[]> {
  const res = await fetch(`${API}/api/v1/email-accounts`, { credentials: "include" });
  if (!res.ok) throw new Error("Failed to load accounts.");
  return res.json();
}

async function disconnectAccount(id: number): Promise<void> {
  const res = await fetch(`${API}/api/v1/email-accounts/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to disconnect account.");
}

async function connectICloud(email: string, appPassword: string): Promise<EmailAccount> {
  const res = await fetch(`${API}/api/v1/email-accounts/icloud`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email_address: email, app_password: appPassword }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Connection failed.");
  }
  return res.json();
}

async function connectImap(fields: {
  host: string;
  port: number;
  username: string;
  password: string;
  use_ssl: boolean;
  display_name?: string;
}): Promise<EmailAccount> {
  const res = await fetch(`${API}/api/v1/email-accounts/imap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(fields),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Connection failed.");
  }
  return res.json();
}

// ------------------------------------------------------------------ //
// Constants                                                             //
// ------------------------------------------------------------------ //

const PROVIDER_LABELS: Record<string, string> = {
  gmail: "Gmail",
  outlook: "Outlook",
  icloud: "iCloud",
  imap: "IMAP",
};

// ------------------------------------------------------------------ //
// AccountRow                                                            //
// ------------------------------------------------------------------ //

function AccountRow({
  account,
  onDisconnect,
}: {
  account: EmailAccount;
  onDisconnect: (id: number) => void;
}) {
  return (
    <tr style={rowStyles.tr}>
      <td style={rowStyles.tdEmail}>{account.email_address}</td>
      <td style={rowStyles.tdProvider}>
        {PROVIDER_LABELS[account.provider] ?? account.provider}
      </td>
      <td style={rowStyles.tdAction}>
        <button
          style={rowStyles.trashBtn}
          onClick={() => onDisconnect(account.id)}
          title="Disconnect this account"
          aria-label={`Disconnect ${account.email_address}`}
        >
          <svg width="15" height="15" viewBox="0 0 15 15" fill="none" aria-hidden="true">
            <path d="M5 2V1h5v1H5zm-2 1h9l-.8 10H3.8L3 3zm2 2v6h1V5H5zm3 0v6h1V5H8z"
              fill="currentColor" fillRule="evenodd" clipRule="evenodd" />
          </svg>
        </button>
      </td>
    </tr>
  );
}

const rowStyles: Record<string, React.CSSProperties> = {
  tr: {
    borderBottom: "1px solid var(--border)",
  },
  tdEmail: {
    padding: "0.65rem 1.5rem 0.65rem 0",
    fontSize: "0.875rem",
    color: "var(--text)",
  },
  tdProvider: {
    padding: "0.65rem 1.5rem 0.65rem 0",
    fontSize: "0.875rem",
    color: "var(--muted)",
    whiteSpace: "nowrap",
    width: "90px",
  },
  tdAction: {
    padding: "0.65rem 0",
    textAlign: "right" as const,
    width: "36px",
  },
  trashBtn: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: "28px",
    height: "28px",
    background: "transparent",
    border: "none",
    borderRadius: "6px",
    color: "var(--muted)",
    cursor: "pointer",
    padding: 0,
  },
};

// ------------------------------------------------------------------ //
// iCloud form                                                           //
// ------------------------------------------------------------------ //

function ICloudForm({ onSuccess, onCancel }: { onSuccess: () => void; onCancel: () => void }) {
  const [email, setEmail] = useState("");
  const [appPassword, setAppPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => connectICloud(email, appPassword),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["email-accounts"] }); onSuccess(); },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div style={formStyles.wrapper}>
      <p style={formStyles.help}>
        Generate an <strong>App-Specific Password</strong> at{" "}
        <a href="https://appleid.apple.com" target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
          appleid.apple.com
        </a>{" "}
        → Sign-In and Security → App-Specific Passwords. Do NOT use your Apple ID password.
      </p>
      {error && <div style={formStyles.error}>{error}</div>}
      <label style={formStyles.label}>
        iCloud email
        <input type="email" value={email} onChange={e => setEmail(e.target.value)}
          placeholder="you@icloud.com" required />
      </label>
      <label style={formStyles.label}>
        App-specific password
        <input type="password" value={appPassword} onChange={e => setAppPassword(e.target.value)}
          placeholder="xxxx-xxxx-xxxx-xxxx" required />
      </label>
      <div style={formStyles.actions}>
        <button style={formStyles.cancelBtn} type="button" onClick={onCancel}>Cancel</button>
        <button style={formStyles.submitBtn} type="button"
          disabled={mutation.isPending || !email || !appPassword}
          onClick={() => { setError(null); mutation.mutate(); }}>
          {mutation.isPending ? "Connecting…" : "Connect iCloud"}
        </button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ //
// Generic IMAP form                                                     //
// ------------------------------------------------------------------ //

function ImapForm({ onSuccess, onCancel }: { onSuccess: () => void; onCancel: () => void }) {
  const [host, setHost] = useState("");
  const [port, setPort] = useState("993");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [ssl, setSsl] = useState(true);
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => connectImap({
      host, port: Number(port), username, password,
      use_ssl: ssl, display_name: displayName || undefined,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["email-accounts"] }); onSuccess(); },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div style={formStyles.wrapper}>
      {error && <div style={formStyles.error}>{error}</div>}
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: "0.75rem" }}>
        <label style={formStyles.label}>
          IMAP host
          <input type="text" value={host} onChange={e => setHost(e.target.value)} placeholder="imap.example.com" />
        </label>
        <label style={formStyles.label}>
          Port
          <input type="number" value={port} onChange={e => setPort(e.target.value)} style={{ width: "80px" }} />
        </label>
      </div>
      <label style={formStyles.label}>
        Username / Email
        <input type="text" value={username} onChange={e => setUsername(e.target.value)} placeholder="you@example.com" />
      </label>
      <label style={formStyles.label}>
        Password
        <input type="password" value={password} onChange={e => setPassword(e.target.value)} />
      </label>
      <label style={{ ...formStyles.label, flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
        <input type="checkbox" checked={ssl} onChange={e => setSsl(e.target.checked)}
          style={{ width: "auto" }} />
        Use SSL / TLS
      </label>
      <label style={formStyles.label}>
        Display name (optional)
        <input type="text" value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder="Work email" />
      </label>
      <div style={formStyles.actions}>
        <button style={formStyles.cancelBtn} type="button" onClick={onCancel}>Cancel</button>
        <button style={formStyles.submitBtn} type="button"
          disabled={mutation.isPending || !host || !username || !password}
          onClick={() => { setError(null); mutation.mutate(); }}>
          {mutation.isPending ? "Connecting…" : "Connect IMAP"}
        </button>
      </div>
    </div>
  );
}

const formStyles: Record<string, React.CSSProperties> = {
  wrapper: {
    display: "flex",
    flexDirection: "column",
    gap: "0.85rem",
  },
  help: {
    margin: 0,
    fontSize: "0.82rem",
    color: "var(--muted)",
    lineHeight: 1.5,
  },
  error: {
    background: "var(--alert-soft)",
    color: "var(--alert)",
    borderRadius: "8px",
    padding: "0.5rem 0.8rem",
    fontSize: "0.82rem",
  },
  label: {
    display: "flex",
    flexDirection: "column",
    gap: "0.25rem",
    fontSize: "0.83rem",
    fontWeight: 600,
    color: "var(--text)",
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: "0.5rem",
    marginTop: "0.25rem",
  },
  cancelBtn: {
    padding: "0.4rem 0.9rem",
    background: "transparent",
    border: "1px solid var(--border)",
    borderRadius: "6px",
    fontSize: "0.83rem",
    cursor: "pointer",
    color: "var(--muted)",
  },
  submitBtn: {
    padding: "0.4rem 0.9rem",
    background: "var(--accent)",
    color: "#fff",
    border: "none",
    borderRadius: "6px",
    fontSize: "0.83rem",
    fontWeight: 700,
    cursor: "pointer",
  },
};

// ------------------------------------------------------------------ //
// Add Account Modal                                                     //
// ------------------------------------------------------------------ //

type ModalStep = "pick" | "icloud" | "imap";

function AddAccountModal({
  onSuccess,
  onClose,
}: {
  onSuccess: () => void;
  onClose: () => void;
}) {
  const [step, setStep] = useState<ModalStep>("pick");

  function handleSuccess() {
    onSuccess();
    onClose();
  }

  return (
    <>
      {/* Backdrop */}
      <div
        style={modalStyles.backdrop}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Dialog */}
      <div role="dialog" aria-modal="true" aria-label="Add email account" style={modalStyles.dialog}>
        {/* Header */}
        <div style={modalStyles.header}>
          <span style={modalStyles.title}>
            {step === "pick" && "Add email account"}
            {step === "icloud" && "Connect iCloud"}
            {step === "imap" && "Connect IMAP"}
          </span>
          <button style={modalStyles.closeBtn} onClick={onClose} aria-label="Close">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div style={modalStyles.body}>
          {step === "pick" && (
            <div style={modalStyles.providerList}>
              <ProviderOption
                label="Gmail"
                description="Google account via OAuth"
                onClick={() => { window.location.href = `${API}/api/v1/email-accounts/gmail/connect`; }}
              />
              <ProviderOption
                label="Outlook"
                description="Microsoft account via OAuth"
                onClick={() => { window.location.href = `${API}/api/v1/email-accounts/outlook/connect`; }}
              />
              <ProviderOption
                label="iCloud"
                description="Apple account with app-specific password"
                onClick={() => setStep("icloud")}
              />
              <ProviderOption
                label="IMAP"
                description="Any mail server via IMAP"
                onClick={() => setStep("imap")}
              />
            </div>
          )}

          {step === "icloud" && (
            <ICloudForm onSuccess={handleSuccess} onCancel={() => setStep("pick")} />
          )}

          {step === "imap" && (
            <ImapForm onSuccess={handleSuccess} onCancel={() => setStep("pick")} />
          )}
        </div>
      </div>
    </>
  );
}

function ProviderOption({
  label,
  description,
  onClick,
}: {
  label: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick} style={modalStyles.providerOption}>
      <span style={modalStyles.providerLabel}>{label}</span>
      <span style={modalStyles.providerDesc}>{description}</span>
    </button>
  );
}

const modalStyles: Record<string, React.CSSProperties> = {
  backdrop: {
    position: "fixed",
    inset: 0,
    background: "rgba(0,0,0,0.35)",
    zIndex: 100,
  },
  dialog: {
    position: "fixed",
    top: "50%",
    left: "50%",
    transform: "translate(-50%, -50%)",
    zIndex: 101,
    background: "var(--surface, #fff)",
    border: "1px solid var(--border)",
    borderRadius: "12px",
    width: "min(420px, calc(100vw - 2rem))",
    boxShadow: "0 8px 32px rgba(0,0,0,0.12)",
    overflow: "hidden",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "1rem 1.1rem 0.75rem",
    borderBottom: "1px solid var(--border)",
  },
  title: {
    fontSize: "0.92rem",
    fontWeight: 700,
    color: "var(--text)",
  },
  closeBtn: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: "28px",
    height: "28px",
    background: "transparent",
    border: "none",
    borderRadius: "6px",
    color: "var(--muted)",
    cursor: "pointer",
    padding: 0,
  },
  body: {
    padding: "1rem 1.1rem 1.1rem",
  },
  providerList: {
    display: "flex",
    flexDirection: "column",
    gap: "0.4rem",
  },
  providerOption: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    gap: "0.15rem",
    padding: "0.65rem 0.85rem",
    background: "transparent",
    border: "1px solid var(--border)",
    borderRadius: "8px",
    cursor: "pointer",
    textAlign: "left" as const,
    width: "100%",
  },
  providerLabel: {
    fontSize: "0.875rem",
    fontWeight: 600,
    color: "var(--text)",
  },
  providerDesc: {
    fontSize: "0.78rem",
    color: "var(--muted)",
  },
};

// ------------------------------------------------------------------ //
// Main component                                                        //
// ------------------------------------------------------------------ //

export function ConnectedAccounts({ connectedParam }: { connectedParam?: string | null }) {
  const qc = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(
    connectedParam ? `${PROVIDER_LABELS[connectedParam] ?? connectedParam} account connected!` : null
  );

  const { data: accounts = [], isLoading } = useQuery({
    queryKey: ["email-accounts"],
    queryFn: fetchAccounts,
  });

  const disconnectMutation = useMutation({
    mutationFn: disconnectAccount,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["email-accounts"] }),
  });

  function handleSuccess() {
    setSuccessMsg("Account connected successfully!");
    setTimeout(() => setSuccessMsg(null), 4000);
  }

  return (
    <section style={sectionStyles.section}>
      <div style={sectionStyles.header}>
        <div>
          <h2 style={sectionStyles.title}>Connected Accounts</h2>
          <p style={sectionStyles.subtitle}>
            Connect email accounts to sync. Multiple accounts and providers supported.
          </p>
        </div>
        <button style={sectionStyles.addBtn} type="button" onClick={() => setShowModal(true)}>
          + Add account
        </button>
      </div>

      {successMsg && (
        <div style={sectionStyles.success}>{successMsg}</div>
      )}

      {/* Account list */}
      {isLoading ? (
        <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>Loading…</p>
      ) : accounts.length === 0 ? (
        <p style={sectionStyles.empty}>No accounts connected yet.</p>
      ) : (
        <table style={sectionStyles.table}>
          <thead>
            <tr>
              <th style={sectionStyles.th}>Email</th>
              <th style={sectionStyles.th}>Provider</th>
              <th style={sectionStyles.th} />
            </tr>
          </thead>
          <tbody>
            {accounts.map((acc) => (
              <AccountRow
                key={acc.id}
                account={acc}
                onDisconnect={(id) => disconnectMutation.mutate(id)}
              />
            ))}
          </tbody>
        </table>
      )}

      {/* Modal */}
      {showModal && (
        <AddAccountModal
          onSuccess={handleSuccess}
          onClose={() => setShowModal(false)}
        />
      )}
    </section>
  );
}

const sectionStyles: Record<string, React.CSSProperties> = {
  section: {
    display: "flex",
    flexDirection: "column",
    gap: "1rem",
  },
  header: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: "1rem",
  },
  title: {
    margin: 0,
    fontSize: "1rem",
    fontWeight: 700,
    color: "var(--text)",
  },
  subtitle: {
    margin: "0.2rem 0 0",
    fontSize: "0.82rem",
    color: "var(--muted)",
  },
  addBtn: {
    flexShrink: 0,
    padding: "0.4rem 0.9rem",
    background: "transparent",
    border: "1px solid var(--border)",
    borderRadius: "6px",
    color: "var(--text)",
    fontSize: "0.83rem",
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  empty: {
    margin: 0,
    fontSize: "0.85rem",
    color: "var(--muted)",
    fontStyle: "italic",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse" as const,
    fontSize: "0.875rem",
  },
  th: {
    padding: "0 0.75rem 0.5rem 0",
    textAlign: "left" as const,
    fontSize: "0.75rem",
    fontWeight: 600,
    color: "var(--muted)",
    borderBottom: "1px solid var(--border)",
    textTransform: "uppercase" as const,
    letterSpacing: "0.05em",
  },
  success: {
    background: "var(--accent-soft)",
    color: "var(--accent)",
    border: "1px solid rgba(15,118,110,0.25)",
    borderRadius: "8px",
    padding: "0.5rem 0.9rem",
    fontSize: "0.85rem",
    fontWeight: 600,
  },
};
