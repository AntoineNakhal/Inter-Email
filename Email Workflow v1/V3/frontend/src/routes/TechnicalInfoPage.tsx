import { KnowledgeBaseSection } from "../features/knowledge/KnowledgeBaseSection";

/**
 * Technical Information page.
 *
 * Hosts the Knowledge Base UI (upload, review modal, document list). Lives
 * on its own route so users can manage the KB without diving into Settings.
 *
 * Layout intentionally mirrors the Settings page so the visual language is
 * consistent — same `page stack sp-page` shell, same header pattern, same
 * `sp-section` building blocks. The KnowledgeBaseSection itself is a
 * single self-contained block that we drop in here; if we add more blocks
 * to this page later (e.g. organization-wide tagging rules) they slot in
 * the same way.
 */
export function TechnicalInfoPage() {
  return (
    <section className="page stack sp-page">
      <div className="sp-header">
        <div className="sp-header__left">
          <p className="sp-header__eyebrow">Technical information</p>
          <h1 className="sp-header__title">Product knowledge base</h1>
          <p className="sp-header__sub">
            Upload technical documentation and the AI will use it to ground
            email analyses and replies in real product facts.
          </p>
        </div>
      </div>
      <div className="sp-divider" />

      <div className="sp-body">
        <KnowledgeBaseSection />
      </div>
    </section>
  );
}
