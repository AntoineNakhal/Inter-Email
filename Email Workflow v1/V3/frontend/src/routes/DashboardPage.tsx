import { Link } from "react-router-dom";

import { useContactStats, useQueueDashboard } from "../hooks/useApi";
import type { EmailThread } from "../types/api";

// ─── helpers ─────────────────────────────────────────────────────────────────

const CATEGORIES = [
  { key: "Urgent / Executive",   label: "Urgent / Executive",  accent: "var(--alert)" },
  { key: "Customer / Partner",   label: "Customer / Partner",  accent: "#185FA5" },
  { key: "Finance / Admin",      label: "Finance / Admin",     accent: "#854F0B" },
  { key: "Events / Logistics",   label: "Events / Logistics",  accent: "#3B6D11" },
  { key: "FYI / Low Priority",   label: "FYI / Low",           accent: "var(--muted)" },
] as const;

const URGENCY_ORDER = ["high", "medium", "low", "unknown"] as const;
type Urgency = typeof URGENCY_ORDER[number];

const URGENCY_COLOR: Record<Urgency, string> = {
  high:    "var(--alert)",
  medium:  "var(--warn)",
  low:     "var(--accent)",
  unknown: "var(--muted)",
};

function urgencyRank(t: EmailThread): number {
  const u = (t.analysis?.urgency ?? "unknown") as Urgency;
  return URGENCY_ORDER.indexOf(u);
}

function isActive(t: EmailThread) {
  return !t.seen_state?.seen && !t.resolved_or_closed;
}

function threadsForCategory(threads: EmailThread[], categoryKey: string) {
  return threads
    .filter((t) => isActive(t) && t.analysis?.category === categoryKey)
    .sort((a, b) => urgencyRank(a) - urgencyRank(b))
    .slice(0, 3);
}

// ─── sub-components ───────────────────────────────────────────────────────────

function CommandCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: number;
  sub: string;
  accent?: string;
}) {
  return (
    <div className="db-cmd">
      <p className="db-cmd__label">{label}</p>
      <p className="db-cmd__value" style={{ color: accent }}>{value}</p>
      <p className="db-cmd__sub">{sub}</p>
    </div>
  );
}

function ThreadMiniRow({ thread }: { thread: EmailThread }) {
  const urgency = (thread.analysis?.urgency ?? "unknown") as Urgency;
  return (
    <Link to={`/threads/${thread.thread_id}`} className="db-mini-row">
      <span
        className="db-mini-row__dot"
        style={{ background: URGENCY_COLOR[urgency] }}
      />
      <span className="db-mini-row__subject">{thread.subject || "Untitled"}</span>
      <span className="db-mini-row__action">
        {thread.analysis?.next_action ?? "Review thread"}
      </span>
    </Link>
  );
}

function CategorySpotlightRow({
  threads,
  categoryKey,
  label,
  accent,
}: {
  threads: EmailThread[];
  categoryKey: string;
  label: string;
  accent: string;
}) {
  const top = threadsForCategory(threads, categoryKey);
  return (
    <div className="db-srow">
      <div className="db-srow__cat">
        <span className="db-srow__dot" style={{ background: accent }} />
        <span className="db-srow__label">{label}</span>
      </div>
      <div className="db-srow__chips">
        {top.length > 0 ? top.map((t) => {
          const urgency = (t.analysis?.urgency ?? "unknown") as Urgency;
          return (
            <Link key={t.thread_id} to={`/threads/${t.thread_id}`} className="db-chip">
              <span className="db-chip__top">
                <span className="db-chip__dot" style={{ background: URGENCY_COLOR[urgency] }} />
                <span className="db-chip__subject">{t.subject || "Untitled"}</span>
              </span>
              <span className="db-chip__action">
                {t.analysis?.next_action ?? "Review thread"}
              </span>
            </Link>
          );
        }) : (
          <span className="db-srow__empty">All clear</span>
        )}
      </div>
    </div>
  );
}

function UrgencyDonut({ threads }: { threads: EmailThread[] }) {
  const active = threads.filter(isActive);
  const counts = {
    high:    active.filter((t) => t.analysis?.urgency === "high").length,
    medium:  active.filter((t) => t.analysis?.urgency === "medium").length,
    low:     active.filter((t) => t.analysis?.urgency === "low").length,
    unknown: active.filter((t) => !t.analysis?.urgency || t.analysis.urgency === "unknown").length,
  };
  const total = active.length || 1;

  const segments: { key: Urgency; label: string }[] = [
    { key: "high",    label: "High" },
    { key: "medium",  label: "Medium" },
    { key: "low",     label: "Low" },
    { key: "unknown", label: "Unknown" },
  ];

  // Build SVG donut segments
  const r = 36;
  const cx = 44;
  const cy = 44;
  const circ = 2 * Math.PI * r;
  let offset = 0;
  const arcs = segments.map(({ key }) => {
    const pct = counts[key] / total;
    const dash = pct * circ;
    const arc = { key, dash, gap: circ - dash, offset, pct };
    offset += dash;
    return arc;
  });

  return (
    <div className="db-chart">
      <p className="db-chart__title">Urgency breakdown</p>
      <div className="db-donut-wrap">
        <svg width="88" height="88" viewBox="0 0 88 88">
          {arcs.map(({ key, dash, gap, offset: off }) => (
            <circle
              key={key}
              r={r} cx={cx} cy={cy}
              fill="none"
              stroke={URGENCY_COLOR[key as Urgency]}
              strokeWidth="10"
              strokeDasharray={`${dash} ${gap}`}
              strokeDashoffset={-off + circ / 4}
              opacity={dash < 0.5 ? 0 : 1}
            />
          ))}
          <text x={cx} y={cy + 2} textAnchor="middle" dominantBaseline="middle"
            style={{ fontSize: "13px", fontWeight: 600, fill: "var(--text)" }}>
            {active.length}
          </text>
          <text x={cx} y={cy + 14} textAnchor="middle" dominantBaseline="middle"
            style={{ fontSize: "8px", fill: "var(--muted)" }}>
            active
          </text>
        </svg>
        <div className="db-donut-legend">
          {segments.map(({ key, label }) => (
            <div key={key} className="db-legend-row">
              <span className="db-legend-dot" style={{ background: URGENCY_COLOR[key as Urgency] }} />
              <span className="db-legend-label">{label}</span>
              <span className="db-legend-val">{counts[key as Urgency]}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function CategoryBar({ threads }: { threads: EmailThread[] }) {
  const active = threads.filter(isActive);
  const data = CATEGORIES.map(({ key, label, accent }) => ({
    label,
    accent,
    count: active.filter((t) => t.analysis?.category === key).length,
  }));
  const max = Math.max(...data.map((d) => d.count), 1);

  return (
    <div className="db-chart">
      <p className="db-chart__title">By category</p>
      <div className="db-bar-list">
        {data.map(({ label, accent, count }) => (
          <div key={label} className="db-bar-row">
            <span className="db-bar-label">{label}</span>
            <div className="db-bar-track">
              <div
                className="db-bar-fill"
                style={{ width: `${(count / max) * 100}%`, background: accent }}
              />
            </div>
            <span className="db-bar-val">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function QueueHealth({ threads }: { threads: EmailThread[] }) {
  const done      = threads.filter((t) => t.seen_state?.seen || t.resolved_or_closed).length;
  const actNow    = threads.filter((t) => isActive(t) && t.analysis?.needs_action_today).length;
  const waiting   = threads.filter((t) => isActive(t) && t.waiting_on_us && !t.analysis?.needs_action_today).length;
  const monitor   = threads.filter((t) => isActive(t) && !t.waiting_on_us && !t.analysis?.needs_action_today).length;
  const total     = threads.length || 1;

  const segments = [
    { label: "Act Now",  count: actNow,  color: "var(--alert)" },
    { label: "Waiting",  count: waiting, color: "var(--warn)" },
    { label: "Monitor",  count: monitor, color: "rgba(20,32,44,0.15)" },
    { label: "Done",     count: done,    color: "var(--accent)" },
  ];

  return (
    <div className="db-chart">
      <p className="db-chart__title">Queue health</p>
      <div className="db-health-track">
        {segments.map(({ label, count, color }) => (
          count > 0 ? (
            <div
              key={label}
              className="db-health-seg"
              style={{ flex: count / total, background: color }}
              title={`${label}: ${count}`}
            />
          ) : null
        ))}
      </div>
      <div className="db-health-legend">
        {segments.map(({ label, count, color }) => (
          <div key={label} className="db-legend-row">
            <span className="db-legend-dot" style={{ background: color }} />
            <span className="db-legend-label">{label}</span>
            <span className="db-legend-val">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── page ─────────────────────────────────────────────────────────────────────

const TYPE_COLOR: Record<string, string> = {
  internal:   "var(--accent)",
  partner:    "#185FA5",
  service:    "#534ab7",
  government: "#3B6D11",
  external:   "var(--muted)",
};

export function DashboardPage() {
  const { data, isLoading } = useQueueDashboard();
  const { data: contactStats } = useContactStats();
  const threads = data?.threads ?? [];
  const active  = threads.filter(isActive);

  const actNow    = active.filter((t) => t.analysis?.needs_action_today).length;
  const waiting   = active.filter((t) => t.waiting_on_us).length;
  const highUrgency = active.filter((t) => t.analysis?.urgency === "high").length;
  const doneCount = threads.filter((t) => t.seen_state?.seen).length;

  return (
    <section className="page db-page">

      <div className="db-header">
        <div>
          <p className="sp-header__eyebrow">Overview</p>
          <h1 className="sp-header__title">Dashboard</h1>
          <p className="sp-header__sub">
            {new Date().toLocaleDateString("en-CA", { weekday: "long", month: "long", day: "numeric" })}
          </p>
        </div>
        <Link to="/inbox" className="sp-connect-btn">Open inbox</Link>
      </div>

      <div className="sp-divider" />

      {isLoading ? (
        <p className="rp-loading">Loading dashboard…</p>
      ) : (
        <>
          {/* Command strip */}
          <div className="db-cmd-strip">
            <CommandCard label="Act Now"     value={actNow}      sub="need action today"  accent="var(--alert)" />
            <CommandCard label="Waiting"     value={waiting}     sub="waiting on reply"   accent="var(--warn)" />
            <CommandCard label="High urgency" value={highUrgency} sub="flagged high"       accent="#b42318" />
            <CommandCard label="Done"        value={doneCount}   sub="handled this cycle" accent="var(--accent)" />
          </div>

          <div className="sp-divider" />

          {/* Category spotlight */}
          <div>
            <p className="db-section-title">Top priorities by category</p>
            <div className="db-spotlight-list">
              {CATEGORIES.map(({ key, label, accent }) => (
                <CategorySpotlightRow
                  key={key}
                  threads={threads}
                  categoryKey={key}
                  label={label}
                  accent={accent}
                />
              ))}
            </div>
          </div>

          <div className="sp-divider" />

          {/* Charts */}
          <div>
            <p className="db-section-title">Queue statistics</p>
            <div className="db-charts-row">
              <UrgencyDonut  threads={threads} />
              <CategoryBar   threads={threads} />
              <QueueHealth   threads={threads} />
            </div>
          </div>

          {contactStats && contactStats.total > 0 && (
            <>
              <div className="sp-divider" />

              {/* Contact stats */}
              <div>
                <p className="db-section-title">Contacts · {contactStats.total} people</p>
                <div className="db-charts-row">

                  {/* Type breakdown */}
                  <div className="db-chart">
                    <p className="db-chart__title">By type</p>
                    <div className="db-bar-list">
                      {Object.entries(contactStats.by_type)
                        .sort(([, a], [, b]) => b - a)
                        .map(([type, count]) => {
                          const max = Math.max(...Object.values(contactStats.by_type), 1);
                          return (
                            <div key={type} className="db-bar-row">
                              <span className="db-bar-label" style={{ textTransform: "capitalize" }}>{type}</span>
                              <div className="db-bar-track">
                                <div className="db-bar-fill" style={{ width: `${(count / max) * 100}%`, background: TYPE_COLOR[type] ?? "var(--muted)" }} />
                              </div>
                              <span className="db-bar-val">{count}</span>
                            </div>
                          );
                        })}
                    </div>
                  </div>

                  {/* New contacts per month */}
                  <div className="db-chart">
                    <p className="db-chart__title">New contacts / month</p>
                    {contactStats.new_per_month.length > 0 ? (
                      <div className="db-month-bars">
                        {(() => {
                          const max = Math.max(...contactStats.new_per_month.map((m) => m.count), 1);
                          return contactStats.new_per_month.map((m) => (
                            <div key={m.month} className="db-month-col">
                              <div className="db-month-bar-wrap">
                                <div
                                  className="db-month-bar-fill"
                                  style={{ height: `${(m.count / max) * 100}%`, background: "var(--accent)" }}
                                  title={`${m.month}: ${m.count}`}
                                />
                              </div>
                              <span className="db-month-label">{m.month.slice(5)}</span>
                            </div>
                          ));
                        })()}
                      </div>
                    ) : (
                      <p className="db-chart__empty">No data yet.</p>
                    )}
                  </div>

                  {/* Top contacts */}
                  <div className="db-chart">
                    <p className="db-chart__title">Most emailed</p>
                    <div className="db-top-list">
                      {contactStats.top_contacts.slice(0, 7).map((c, i) => (
                        <div key={c.email} className="db-top-row">
                          <span className="db-top-rank">{i + 1}</span>
                          <div className="db-top-info">
                            <span className="db-top-name">{c.display_name || c.email}</span>
                            <span className="db-top-org">{c.organization || c.email}</span>
                          </div>
                          <span className="db-top-count" style={{ color: TYPE_COLOR[c.contact_type] ?? "var(--muted)" }}>
                            {c.thread_count}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                </div>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
