const KEY_DISPLAY_NAME = "brse_display_name";
const KEY_LANGUAGE = "brse_preferred_language";

export function saveUserPrefs(name: string, language: string) {
  try {
    if (name.trim()) localStorage.setItem(KEY_DISPLAY_NAME, name.trim());
    if (language) localStorage.setItem(KEY_LANGUAGE, language);
  } catch {
    // localStorage may be unavailable in private browsing
  }
}

export function loadUserPrefs(): { displayName: string; language: string } {
  try {
    return {
      displayName: localStorage.getItem(KEY_DISPLAY_NAME) ?? "",
      language: localStorage.getItem(KEY_LANGUAGE) ?? "",
    };
  } catch {
    return { displayName: "", language: "" };
  }
}
