/**
 * Validates the `next` parameter of /login so sign-in can only return to a
 * MeetQ user route on this origin (no open redirect, no admin realm).
 */
const FALLBACK = "/";

export function safeNextPath(raw: string | null | undefined): string {
  if (!raw) return FALLBACK;
  const value = raw.trim();
  // Only same-origin absolute paths: "/x", never "//host", "/\host" or "scheme:".
  if (!value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return FALLBACK;
  // Control characters (incl. tab/newline) can be stripped by URL parsers into "//host".
  if (/[\u0000-\u001f\u007f\\]/.test(value)) return FALLBACK;

  let url: URL;
  try {
    url = new URL(value, "https://meetq.invalid");
  } catch {
    return FALLBACK;
  }
  if (url.origin !== "https://meetq.invalid") return FALLBACK;
  if (url.pathname === "/login" || url.pathname.startsWith("/admin")) return FALLBACK;
  return `${url.pathname}${url.search}${url.hash}`;
}

export function loginPathFor(next: string): string {
  const target = safeNextPath(next);
  return target === FALLBACK ? "/login" : `/login?next=${encodeURIComponent(target)}`;
}
