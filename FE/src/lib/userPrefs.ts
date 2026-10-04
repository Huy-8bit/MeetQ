const KEY_DISPLAY_NAME = "brse_display_name";
const KEY_LANGUAGE = "brse_preferred_language";

// Display names are remembered per signed-in account so a shared browser never
// pre-fills one person's name for another.
function displayNameKey(userId?: string): string {
  return userId ? `${KEY_DISPLAY_NAME}:${userId}` : KEY_DISPLAY_NAME;
}

/**
 * Remembers the lobby choices. A display name equal to the account name is not
 * stored, so the Google name keeps being used until the person picks another.
 */
export function saveUserPrefs(name: string, language: string, userId?: string, accountName?: string) {
  try {
    const trimmed = name.trim();
    const key = displayNameKey(userId);
    if (trimmed && trimmed !== accountName?.trim()) localStorage.setItem(key, trimmed);
    else if (trimmed && userId) localStorage.removeItem(key);
    if (language) localStorage.setItem(KEY_LANGUAGE, language);
  } catch {
    // localStorage may be unavailable in private browsing
  }
}

export function loadUserPrefs(userId?: string): { displayName: string; language: string } {
  try {
    return {
      displayName: localStorage.getItem(displayNameKey(userId)) ?? "",
      language: localStorage.getItem(KEY_LANGUAGE) ?? "",
    };
  } catch {
    return { displayName: "", language: "" };
  }
}
