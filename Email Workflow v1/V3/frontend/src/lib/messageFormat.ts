const INLINE_REPLACEMENTS: Array<[RegExp, string]> = [
  [/\r\n?/g, "\n"],
  [/\u00a0/g, " "],
  [/[\u200b-\u200d\u2060\ufeff]/g, ""],
  [/\u00c2/g, ""],
  [/\ufffd/g, ""],
];

const FOOTER_MARKERS = [
  "the content of this message",
  "this message and any attachments",
  "this e-mail and any attachments",
  "if you received this message by mistake",
  "if you are not the intended recipient",
  "please reply to this message and delete the email",
  "ce message et toute piece jointe",
  "ce courriel et toute piece jointe",
  "si vous avez recu ce message par erreur",
];

const QUOTED_HISTORY_MARKERS = [
  /^on .+wrote:$/i,
  /^le .+a ecrit.*:$/i,
  /^from:\s/i,
  /^de:\s/i,
  /^sent:\s/i,
  /^envoye:\s/i,
  /^to:\s/i,
  /^a:\s/i,
  /^subject:\s/i,
  /^objet:\s/i,
  /^-+\s*original message\s*-+$/i,
];

function normalizeInlineText(value: string): string {
  let nextValue = value ?? "";
  for (const [pattern, replacement] of INLINE_REPLACEMENTS) {
    nextValue = nextValue.replace(pattern, replacement);
  }
  nextValue = nextValue.replace(/[^\S\n]+/g, " ");
  nextValue = nextValue.replace(/\n{3,}/g, "\n\n");
  return nextValue.trim();
}

function stripBoilerplate(value: string): string {
  const normalized = normalizeInlineText(value);
  const lines = normalized.split("\n");
  const keptLines: string[] = [];

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const lowered = line.trim().toLowerCase();
    const hasVisibleContent = keptLines.some((item) => item.trim().length > 0);

    if (
      hasVisibleContent &&
      QUOTED_HISTORY_MARKERS.some((pattern) => pattern.test(lowered))
    ) {
      break;
    }

    if (hasVisibleContent && FOOTER_MARKERS.some((marker) => lowered.includes(marker))) {
      break;
    }

    keptLines.push(line);
  }

  return keptLines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

export function formatInlineText(value: string | null | undefined): string {
  return normalizeInlineText(value ?? "");
}

export function formatMessageExcerpt(
  body: string | null | undefined,
  snippet: string | null | undefined,
): string {
  const cleanedBody = stripBoilerplate(body ?? "");
  const cleanedSnippet = normalizeInlineText(snippet ?? "");
  const preferred = cleanedBody || cleanedSnippet;
  if (!preferred) {
    return "";
  }

  const compact = preferred.replace(/\n{3,}/g, "\n\n").trim();
  if (compact.length <= 1200) {
    return compact;
  }
  return `${compact.slice(0, 1200).trim()}...`;
}
