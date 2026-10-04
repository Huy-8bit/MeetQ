/**
 * Google Identity Services (GIS) — https://developers.google.com/identity/gsi/web
 * Sign in with Google button, ID-token (credential) callback, popup UX.
 * The credential is only forwarded to the MeetQ backend, which verifies it.
 */
const GIS_SCRIPT_URL = "https://accounts.google.com/gsi/client";

export interface GoogleCredentialResponse {
  credential?: string;
  select_by?: string;
}

interface GoogleIdConfiguration {
  client_id: string;
  callback: (response: GoogleCredentialResponse) => void;
  auto_select?: boolean;
  cancel_on_tap_outside?: boolean;
  ux_mode?: "popup" | "redirect";
  context?: "signin" | "signup" | "use";
  itp_support?: boolean;
  use_fedcm_for_button?: boolean;
}

export interface GoogleButtonOptions {
  type?: "standard" | "icon";
  theme?: "outline" | "filled_blue" | "filled_black";
  size?: "large" | "medium" | "small";
  text?: "signin_with" | "signup_with" | "continue_with" | "signin";
  shape?: "rectangular" | "pill" | "circle" | "square";
  logo_alignment?: "left" | "center";
  width?: number;
  locale?: string;
}

export interface GoogleAccountsId {
  initialize: (config: GoogleIdConfiguration) => void;
  renderButton: (parent: HTMLElement, options: GoogleButtonOptions) => void;
  disableAutoSelect: () => void;
  cancel: () => void;
}

declare global {
  interface Window {
    google?: { accounts?: { id?: GoogleAccountsId } };
  }
}

export function getGoogleClientId(): string | null {
  const value = import.meta.env.VITE_GOOGLE_CLIENT_ID?.trim();
  return value ? value : null;
}

let scriptPromise: Promise<GoogleAccountsId> | null = null;

export function loadGoogleIdentity(): Promise<GoogleAccountsId> {
  const existing = window.google?.accounts?.id;
  if (existing) return Promise.resolve(existing);
  if (scriptPromise) return scriptPromise;

  scriptPromise = new Promise<GoogleAccountsId>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = GIS_SCRIPT_URL;
    script.async = true;
    script.defer = true;
    script.onload = () => {
      const id = window.google?.accounts?.id;
      if (id) resolve(id);
      else reject(new Error("Google Identity Services did not initialize."));
    };
    script.onerror = () => reject(new Error("Couldn't load Google sign-in."));
    document.head.appendChild(script);
  }).catch((error: unknown) => {
    scriptPromise = null; // allow a retry
    throw error;
  });
  return scriptPromise;
}

/** Stop Google from silently re-selecting the account after the user signed out. */
export function disableGoogleAutoSelect(): void {
  try {
    window.google?.accounts?.id?.disableAutoSelect();
  } catch {
    // GIS not loaded: nothing to disable.
  }
}
