/** 75 → "1:15", 3725 → "1:02:05". */
export function formatElapsed(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/** "Expires in 6 days" / "Expires in 5 hours" / "Expired". */
export function formatExpiresIn(expiresAt: string | null | undefined, now = Date.now()): string {
  if (!expiresAt) return "";
  const ms = new Date(expiresAt).getTime() - now;
  if (ms <= 0) return "Expired";
  const hours = ms / 3_600_000;
  if (hours < 1) return "Expires in less than an hour";
  if (hours < 48) return `Expires in ${Math.round(hours)} hours`;
  return `Expires in ${Math.floor(hours / 24)} days`;
}
