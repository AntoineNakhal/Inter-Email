import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useThreads } from "../hooks/useApi";
import { formatDate } from "../lib/format";
import type { EmailThread } from "../types/api";

// ─── contact classification ──────────────────────────────────────────────────

const INTERNAL_DOMAINS = new Set(["inter-op.ca"]);
const SERVICE_DOMAINS = new Set([
  "gmail.com", "google.com", "googlemail.com",
  "microsoft.com", "outlook.com", "hotmail.com", "live.com",
  "openai.com", "anthropic.com",
  "github.com", "slack.com", "notion.so", "figma.com",
  "stripe.com", "aws.amazon.com", "amazonaws.com",
  "zoom.us", "dropbox.com", "hubspot.com", "salesforce.com",
  "mailchimp.com", "sendgrid.com", "twilio.com",
]);
const RECRUITER_HINTS = ["recruit", "talent", "hr ", " hr", "headhunt", "career", "hiring", "candidate"];

type ContactType = "internal" | "partner" | "service" | "recruiter" | "external";

const CONTACT_TYPE_LABEL: Record<ContactType, string> = {
  internal:  "Internal",
  partner:   "Partner",
  service:   "Service",
  recruiter: "Recruiter",
  external:  "External",
};

const CONTACT_TYPE_COLOR: Record<ContactType, string> = {
  internal:  "rgba(15,118,110,0.08)",
  partner:   "rgba(55,138,221,0.08)",
  service:   "rgba(127,119,221,0.08)",
  recruiter: "rgba(217,119,6,0.08)",
  external:  "rgba(20,32,44,0.06)",
};

const CONTACT_TYPE_TEXT: Record<ContactType, string> = {
  internal:  "#0f5d56",
  partner:   "#185FA5",
  service:   "#534ab7",
  recruiter: "#854f0b",
  external:  "var(--muted)",
};

function extractEmail(raw: string): string {
  const match = raw.match(/<([^>]+)>/);
  return match ? match[1].trim() : raw.trim();
}

function domainOf(email: string): string {
  return email.split("@")[1]?.toLowerCase() ?? "";
}

function orgFromDomain(domain: string): string {
  if (!domain) return "—";
  const parts = domain.split(".");
  if (parts.length >= 2) {
    const name = parts[parts.length - 2];
    return name.charAt(0).toUpperCase() + name.slice(1);
  }
  return domain;
}

function classifyThread(thread: EmailThread): {
  type: ContactType;
  keyContact: string;
  organization: string;
} {
  // Use AI CRM data first
  const org = thread.analysis?.crm_company?.trim() || null;
  const contact = thread.analysis?.crm_contact_name?.trim() || null;
  const category = thread.analysis?.category ?? "";
  const subject = (thread.subject ?? "").toLowerCase();
  const combined = `${subject} ${category}`.toLowerCase();

  // Check all participants, find first external one
  const participants = thread.participants ?? [];
  let keyContact = contact ?? "";
  let organization = org ?? "";
  let detectedType: ContactType = "external";

  for (const raw of participants) {
    const email = extractEmail(raw);
    const domain = domainOf(email);
    if (!domain) continue;

    if (INTERNAL_DOMAINS.has(domain)) {
      detectedType = "internal";
      continue; // keep looking for external key contact
    }

    // First external participant becomes key contact
    if (!keyContact) keyContact = email;
    if (!organization) organization = orgFromDomain(domain);

    if (SERVICE_DOMAINS.has(domain)) {
      detectedType = "service";
      break;
    }
    if (RECRUITER_HINTS.some((h) => combined.includes(h))) {
      detectedType = "recruiter";
      break;
    }
    if (category.toLowerCase().includes("customer") || category.toLowerCase().includes("partner")) {
      detectedType = "partner";
      break;
    }
    detectedType = "external";
    break;
  }

  // If all participants are internal
  if (detectedType === "external" && participants.every((r) => INTERNAL_DOMAINS.has(domainOf(extractEmail(r))))) {
    detectedType = "internal";
  }

  return {
    type: detectedType,
    keyContact: keyContact || "—",
    organization: organization || "—",
  };
}

function threadStatus(thread: EmailThread): string {
  if (thread.seen_state?.seen) return "Done";
  if (thread.analysis?.needs_action_today) return "Act Now";
  if (thread.waiting_on_us) return "Waiting";
  if (thread.resolved_or_closed) return "Closed";
  return "Monitor";
}

type SortKey = "subject" | "type" | "org" | "category" | "urgency" | "status" | "messages" | "date";
type SortDir = "asc" | "desc";

const URGENCY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2, unknown: 3 };
const STATUS_RANK: Record<string, number> = { "Act Now": 0, Waiting: 1, Monitor: 2, Closed: 3, Done: 4 };

function sortThreads(
  rows: Array<EmailThread & { _type: ContactType; _contact: string; _org: string }>,
  key: SortKey,
  dir: SortDir,
) {
  const factor = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    let cmp = 0;
    switch (key) {
      case "subject":  cmp = (a.subject ?? "").localeCompare(b.subject ?? ""); break;
      case "type":     cmp = a._type.localeCompare(b._type); break;
      case "org":      cmp = a._org.localeCompare(b._org); break;
      case "category": cmp = (a.analysis?.category ?? "").localeCompare(b.analysis?.category ?? ""); break;
      case "urgency":  cmp = (URGENCY_RANK[a.analysis?.urgency ?? "unknown"] ?? 3) - (URGENCY_RANK[b.analysis?.urgency ?? "unknown"] ?? 3); break;
      case "status":   cmp = (STATUS_RANK[threadStatus(a)] ?? 5) - (STATUS_RANK[threadStatus(b)] ?? 5); break;
      case "messages": cmp = (a.message_count ?? 0) - (b.message_count ?? 0); break;
      case "date":     cmp = new Date(a.latest_message_date ?? 0).getTime() - new Date(b.latest_message_date ?? 0).getTime(); break;
    }
    return cmp * factor;
  });
}

// ─── component ────────────────────────────────────────────────────────────────

export function EmailTablePage() {
  const { data, isLoading } = useThreads();
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<ContactType | "all">("all");
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const rows = useMemo(() => {
    return (data?.threads ?? []).map((t) => {
      const { type, keyContact, organization } = classifyThread(t);
      return { ...t, _type: type, _contact: keyContact, _org: organization };
    });
  }, [data?.threads]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (typeFilter !== "all" && r._type !== typeFilter) return false;
      if (term && !`${r.subject} ${r._contact} ${r._org} ${r.analysis?.category ?? ""}`.toLowerCase().includes(term)) return false;
      return true;
    });
  }, [rows, search, typeFilter]);

  const sorted = useMemo(() => sortThreads(filtered, sortKey, sortDir), [filtered, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "date" ? "desc" : "asc");
    }
  }

  function SortIcon({ k }: { k: SortKey }) {
    if (sortKey !== k) return <span className="et-sort-icon et-sort-icon--idle">⇅</span>;
    return <span className="et-sort-icon">{sortDir === "asc" ? "↑" : "↓"}</span>;
  }

  return (
    <section className="page et-page">
      <div className="db-header">
        <div>
          <p className="sp-header__eyebrow">Contacts</p>
          <h1 className="sp-header__title">Email Table</h1>
          <p className="sp-header__sub">All threads you're involved in, enriched with AI context.</p>
        </div>
        <span className="rp-header__count">{sorted.length} threads</span>
      </div>

      <div className="sp-divider" />

      <div className="et-toolbar">
        <input
          className="inbox-toolbar__search"
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search subject, contact, organisation…"
          style={{ flex: 1 }}
        />
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as ContactType | "all")}>
          <option value="all">All types</option>
          {(Object.keys(CONTACT_TYPE_LABEL) as ContactType[]).map((t) => (
            <option key={t} value={t}>{CONTACT_TYPE_LABEL[t]}</option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <p className="rp-loading">Loading…</p>
      ) : (
        <div className="et-wrap">
          <table className="et-table">
            <thead>
              <tr>
                {([
                  ["subject",  "Subject"],
                  ["type",     "Type"],
                  ["org",      "Organisation"],
                  ["category", "Category"],
                  ["urgency",  "Urgency"],
                  ["status",   "Status"],
                  ["messages", "Msg"],
                  ["date",     "Date"],
                ] as [SortKey, string][]).map(([k, label]) => (
                  <th key={k} className="et-th" onClick={() => toggleSort(k)}>
                    {label} <SortIcon k={k} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => {
                const urgency = row.analysis?.urgency ?? "unknown";
                const urgencyColor = urgency === "high" ? "var(--alert)" : urgency === "medium" ? "var(--warn)" : "var(--muted)";
                const status = threadStatus(row);
                return (
                  <tr key={row.thread_id} className="et-row">
                    <td className="et-td et-td--subject">
                      <Link to={`/threads/${row.thread_id}`} className="et-link">
                        {row.subject || "Untitled thread"}
                      </Link>
                    </td>
                    <td className="et-td">
                      <span
                        className="et-badge"
                        style={{
                          background: CONTACT_TYPE_COLOR[row._type],
                          color: CONTACT_TYPE_TEXT[row._type],
                        }}
                      >
                        {CONTACT_TYPE_LABEL[row._type]}
                      </span>
                    </td>
                    <td className="et-td et-td--org">{row._org}</td>
                    <td className="et-td et-td--cat">{row.analysis?.category ?? "—"}</td>
                    <td className="et-td">
                      <span style={{ color: urgencyColor, fontSize: "0.78rem", fontWeight: 500 }}>
                        {urgency !== "unknown" ? urgency : "—"}
                      </span>
                    </td>
                    <td className="et-td">
                      <span className="et-status">{status}</span>
                    </td>
                    <td className="et-td et-td--num">{row.message_count}</td>
                    <td className="et-td et-td--date">{formatDate(row.latest_message_date)}</td>
                  </tr>
                );
              })}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={8} className="et-empty">No threads match your filters.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
