export type AppThemeMode = "light" | "dark";
export type RoomLayoutMode = "stage-focus" | "balanced" | "compact";

const ROOM_LAYOUT_STORAGE_KEY = "brseai_room_layout_mode";

const DEFAULT_ROOM_LAYOUT_MODE: RoomLayoutMode = "balanced";

function getOsTheme(): AppThemeMode {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyThemePreference(theme: AppThemeMode): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.setProperty("color-scheme", theme);
}

export function initThemePreference(): AppThemeMode {
  const theme = getOsTheme();
  applyThemePreference(theme);

  if (typeof window !== "undefined") {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
      applyThemePreference(e.matches ? "dark" : "light");
    });
  }

  return theme;
}

export function loadThemePreference(): AppThemeMode {
  return getOsTheme();
}

export function saveThemePreference(_theme: AppThemeMode): void {
  // Theme is driven by OS; no manual override saved.
}

export function loadRoomLayoutPreference(): RoomLayoutMode {
  if (typeof window === "undefined") {
    return DEFAULT_ROOM_LAYOUT_MODE;
  }

  const stored = readStorageValue(ROOM_LAYOUT_STORAGE_KEY);
  return isRoomLayoutMode(stored) ? stored : DEFAULT_ROOM_LAYOUT_MODE;
}

export function saveRoomLayoutPreference(layout: RoomLayoutMode): void {
  if (typeof window === "undefined") {
    return;
  }

  writeStorageValue(ROOM_LAYOUT_STORAGE_KEY, layout);
}

function readStorageValue(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorageValue(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Preference persistence is optional; runtime UI should continue if storage is blocked.
  }
}

function isAppThemeMode(value: string | null): value is AppThemeMode {
  return value === "light" || value === "dark";
}

function isRoomLayoutMode(value: string | null): value is RoomLayoutMode {
  return value === "stage-focus" || value === "balanced" || value === "compact";
}
