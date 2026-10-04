import { useEffect, useRef, useState } from "react";
import { Spinner } from "../components/ui/Spinner";
import { getGoogleClientId, loadGoogleIdentity, type GoogleCredentialResponse } from "./google";

interface GoogleSignInButtonProps {
  /** Receives the Google ID token. It is sent to the backend, never trusted here. */
  onCredential: (credential: string) => void;
  onError: (message: string) => void;
  disabled?: boolean;
}

const BUTTON_WIDTH = 320;

/** Google's own "Continue with Google" button (Google Identity Services, popup mode). */
export function GoogleSignInButton({ onCredential, onError, disabled = false }: GoogleSignInButtonProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onCredential, onError });
  callbacks.current = { onCredential, onError };
  const [ready, setReady] = useState(false);
  const clientId = getGoogleClientId();

  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;
    loadGoogleIdentity()
      .then((googleId) => {
        if (cancelled || !containerRef.current) return;
        googleId.initialize({
          client_id: clientId,
          ux_mode: "popup",
          auto_select: false,
          cancel_on_tap_outside: true,
          context: "signin",
          itp_support: true,
          use_fedcm_for_button: true,
          callback: (response: GoogleCredentialResponse) => {
            if (response.credential) callbacks.current.onCredential(response.credential);
            else callbacks.current.onError("Google didn't return a sign-in credential. Try again.");
          },
        });
        const dark = document.documentElement.dataset.theme === "dark";
        googleId.renderButton(containerRef.current, {
          type: "standard",
          theme: dark ? "filled_black" : "outline",
          size: "large",
          text: "continue_with",
          shape: "pill",
          logo_alignment: "left",
          width: Math.min(BUTTON_WIDTH, containerRef.current.clientWidth || BUTTON_WIDTH),
        });
        setReady(true);
      })
      .catch(() => {
        if (!cancelled) callbacks.current.onError("Couldn't load Google sign-in. Check your connection and reload.");
      });
    return () => {
      cancelled = true;
    };
  }, [clientId]);

  if (!clientId) return null;

  return (
    <div className="google-signin" aria-busy={!ready} data-disabled={disabled || undefined}>
      {!ready ? (
        <span className="google-signin-loading">
          <Spinner /> Loading Google sign-in…
        </span>
      ) : null}
      <div ref={containerRef} className="google-signin-button" />
    </div>
  );
}
