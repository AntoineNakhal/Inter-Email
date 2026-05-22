import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";

const API = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? "Login failed.");
      }
      navigate("/home", { replace: true });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <div style={styles.brand}>
          <span style={styles.brandName}>INTER-OP</span>
          <p style={styles.brandSub}>Email Workflow</p>
        </div>

        <h1 style={styles.title}>Sign in</h1>

        {error && <div style={styles.errorBox}>{error}</div>}

        <form onSubmit={handleSubmit} style={styles.form}>
          <label style={styles.label}>
            Email
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={styles.input}
            />
          </label>
          <label style={styles.label}>
            Password
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={styles.input}
            />
          </label>
          <button type="submit" disabled={loading} style={styles.btn}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p style={styles.footer}>
          No account?{" "}
          <Link to="/register" style={styles.link}>
            Create one
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
  input: {
    // inherits from global styles.css
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
