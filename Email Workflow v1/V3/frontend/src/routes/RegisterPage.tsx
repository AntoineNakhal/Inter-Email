import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";

const API = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function RegisterPage() {
  const navigate = useNavigate();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/v1/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password, display_name: displayName }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? "Registration failed.");
      }
      navigate("/settings", { replace: true });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Registration failed.");
    } finally {
      setLoading(false);
    }
  }

  const passwordOk = password.length === 0 || password.length >= 8;
  const confirmOk = confirm.length === 0 || password === confirm;

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <div style={styles.brand}>
          <span style={styles.brandName}>INTER-OP</span>
          <p style={styles.brandSub}>Email Workflow</p>
        </div>

        <h1 style={styles.title}>Create account</h1>

        {error && <div style={styles.errorBox}>{error}</div>}

        <form onSubmit={handleSubmit} style={styles.form}>
          <label style={styles.label}>
            Display name
            <input
              type="text"
              autoComplete="name"
              required
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </label>
          <label style={styles.label}>
            Email
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label style={styles.label}>
            Password
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={!passwordOk ? { borderColor: "var(--alert)" } : undefined}
            />
            {!passwordOk && (
              <span style={styles.hint}>At least 8 characters required.</span>
            )}
          </label>
          <label style={styles.label}>
            Confirm password
            <input
              type="password"
              autoComplete="new-password"
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              style={!confirmOk ? { borderColor: "var(--alert)" } : undefined}
            />
            {!confirmOk && (
              <span style={styles.hint}>Passwords don't match.</span>
            )}
          </label>
          <button
            type="submit"
            disabled={loading || !passwordOk || !confirmOk}
            style={{
              ...styles.btn,
              opacity: loading || !passwordOk || !confirmOk ? 0.6 : 1,
            }}
          >
            {loading ? "Creating account…" : "Create account"}
          </button>
        </form>

        <p style={styles.footer}>
          Already have an account?{" "}
          <Link to="/login" style={styles.link}>
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "1.5rem",
  },
  card: {
    width: "100%",
    maxWidth: "420px",
    background: "var(--surface-strong)",
    borderRadius: "16px",
    padding: "2.5rem 2rem",
    boxShadow: "var(--shadow)",
    border: "1px solid var(--border)",
  },
  brand: {
    textAlign: "center",
    marginBottom: "2rem",
  },
  brandName: {
    fontSize: "1.1rem",
    fontWeight: 800,
    letterSpacing: "0.08em",
    color: "var(--text)",
  },
  brandSub: {
    margin: "0.15rem 0 0",
    fontSize: "0.8rem",
    color: "var(--muted)",
  },
  title: {
    margin: "0 0 1.5rem",
    fontSize: "1.35rem",
    fontWeight: 700,
    color: "var(--text)",
  },
  errorBox: {
    background: "var(--alert-soft)",
    color: "var(--alert)",
    border: "1px solid rgba(180,35,24,0.2)",
    borderRadius: "8px",
    padding: "0.6rem 0.9rem",
    fontSize: "0.85rem",
    marginBottom: "1rem",
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: "1rem",
  },
  label: {
    display: "flex",
    flexDirection: "column",
    gap: "0.3rem",
    fontSize: "0.85rem",
    fontWeight: 600,
    color: "var(--text)",
  },
  hint: {
    fontSize: "0.75rem",
    color: "var(--alert)",
    marginTop: "0.1rem",
  },
  btn: {
    marginTop: "0.5rem",
    padding: "0.65rem 1.2rem",
    background: "var(--accent)",
    color: "#fff",
    border: "none",
    borderRadius: "8px",
    fontWeight: 700,
    fontSize: "0.9rem",
    cursor: "pointer",
    transition: "opacity 0.15s",
  },
  footer: {
    marginTop: "1.5rem",
    textAlign: "center",
    fontSize: "0.85rem",
    color: "var(--muted)",
  },
  link: {
    color: "var(--accent)",
    fontWeight: 600,
    textDecoration: "underline",
  },
};
