import { useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown, faBookOpen } from "@fortawesome/free-solid-svg-icons";

import type { KbDraftSource } from "../../types/api";

type Props = {
  sources: KbDraftSource[];
};

/**
 * Shows the KB chunks the AI received as context for this draft.
 * Each source is collapsed by default — click to read the exact snippet
 * the model saw.
 */
export function DraftKbSourcesPanel({ sources }: Props) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const toggle = (id: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  if (!sources || sources.length === 0) {
    return (
      <div className="kb-sources kb-sources--empty">
        <p className="kb-sources__empty-label">No knowledge base sources used</p>
      </div>
    );
  }

  return (
    <div className="kb-sources">
      <p className="kb-sources__heading">
        <FontAwesomeIcon icon={faBookOpen} className="kb-sources__heading-icon" />
        Sources used
        <span className="kb-sources__badge">{sources.length}</span>
      </p>
      <ul className="kb-sources__list">
        {sources.map((source) => {
          const isOpen = expanded.has(source.chunk_id);
          const label =
            source.product_name && source.product_name !== source.document_title
              ? `${source.product_name} — ${source.document_title}`
              : source.document_title;
          return (
            <li key={source.chunk_id} className={`kb-sources__item${isOpen ? " kb-sources__item--open" : ""}`}>
              <button
                type="button"
                className="kb-sources__trigger"
                onClick={() => toggle(source.chunk_id)}
                aria-expanded={isOpen}
              >
                <span className="kb-sources__doc-label">{label}</span>
                <FontAwesomeIcon
                  icon={faChevronDown}
                  className={`kb-sources__chevron${isOpen ? " kb-sources__chevron--open" : ""}`}
                />
              </button>
              {isOpen && (
                <p className="kb-sources__body">{source.content_preview}</p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
