export function extractRoomId(input: string): string | null {
  const raw = input.trim();
  if (!raw) {
    return null;
  }

  if (/^rm_[a-zA-Z0-9]+$/.test(raw)) {
    return raw;
  }

  try {
    const url = new URL(raw);
    const match = url.pathname.match(/\/rooms\/(rm_[a-zA-Z0-9]+)/);
    return match?.[1] ?? null;
  } catch {
    const match = raw.match(/(rm_[a-zA-Z0-9]+)/);
    return match?.[1] ?? null;
  }
}
