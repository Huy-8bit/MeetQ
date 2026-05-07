export type AppThemeMode = "light" | "dark";
export type RoomLayoutMode = "stage-focus" | "balanced" | "compact";

const THEME_STORAGE_KEY = "brseai_theme_mode";
const ROOM_LAYOUT_STORAGE_KEY = "brseai_room_layout_mode";

const DEFAULT_THEME_MODE: AppThemeMode = "dark";
const DEFAULT_ROOM_LAYOUT_MODE: RoomLayoutMode = "balanced";

export function loadThemePreference(): AppThemeMode {
  if (typeof window === "undefined") {
    return DEFAULT_THEME_MODE;
  }

  const stored = readStorageValue(THEME_STORAGE_KEY);
  return isAppThemeMode(stored) ? stored : DEFAULT_THEME_MODE;
}

export function saveThemePreference(theme: AppThemeMode): void {
  if (typeof window === "undefined") {
    return;
  }

  writeStorageValue(THEME_STORAGE_KEY, theme);
}

export function applyThemePreference(theme: AppThemeMode): void {
  if (typeof document === "undefined") {
    return;
  }

  document.documentElement.dataset.theme = theme;
  document.documentElement.style.setProperty("color-scheme", theme);
}

export function initThemePreference(): AppThemeMode {
  const theme = loadThemePreference();
  applyThemePreference(theme);
  return theme;
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
