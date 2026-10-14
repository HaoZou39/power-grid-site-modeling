const SAFE_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);

export function safeMarkdownUrl(url: string): string {
  const value = url.trim();
  if (!value) return "";
  if (/^(?:[/?#.]|\.\.?\/)/.test(value)) return value;
  try {
    const parsed = new URL(value);
    return SAFE_PROTOCOLS.has(parsed.protocol) ? value : "";
  } catch {
    return "";
  }
}
