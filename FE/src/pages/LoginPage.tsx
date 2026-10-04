import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Spinner } from "../components/ui/Spinner";
import { SessionNotEstablishedError, useAuth, type AuthNotice } from "../auth/AuthProvider";
import { GoogleSignInButton } from "../auth/GoogleSignInButton";
import { getGoogleClientId } from "../auth/google";
import { safeNextPath } from "../auth/next";
import { ApiError } from "../lib/api";

function signInErrorMessage(error: unknown): string {
  if (error instanceof SessionNotEstablishedError) {
    return "Google confirmed your account, but MeetQ couldn't keep you signed in. Allow cookies for this site and try again.";
  }
  if (error instanceof ApiError) {
    if (error.status === 403) return error.message || "This Google account isn't allowed to use MeetQ.";
    if (error.status === 401) return "Google sign-in couldn't be verified. Try again.";
    if (error.status === 404 || error.status === 501) return "Sign-in isn't available on this MeetQ server yet.";
    if (error.status === 429) return "Too many sign-in attempts. Wait a minute and try again.";
    return "MeetQ couldn't sign you in. Try again.";
  }
  return "Couldn't reach MeetQ. Check your connection and try again.";
}

const NOTICES: Record<Exclude<AuthNotice, null>, { tone: "info" | "warning"; text: string }> = {
  session_ended: { tone: "info", text: "Your session ended. Sign in again to continue." },
  server_unreachable: { tone: "warning", text: "Couldn't reach MeetQ to check your sign-in." },
  auth_unavailable: { tone: "warning", text: "Sign-in isn't available on this MeetQ server yet." },
};

export function LoginPage() {
  const { status, notice, ensureChecked, refresh, signInWithGoogle } = useAuth();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const next = safeNextPath(searchParams.get("next"));
  const [signingIn, setSigningIn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const clientId = getGoogleClientId();
  const joiningRoom = next.startsWith("/rooms/");

  useEffect(() => {
    ensureChecked();
  }, [ensureChecked]);

  if (status === "authenticated" && !signingIn) {
    return <Navigate to={next} replace />;
  }

  async function handleCredential(credential: string) {
    setSigningIn(true);
    setError(null);
    try {
      await signInWithGoogle(credential);
      navigate(next, { replace: true });
    } catch (caught) {
      setError(signInErrorMessage(caught));
      setSigningIn(false);
    }
  }

  const noticeView = notice && !error ? NOTICES[notice] : null;

  return (
    <div className="auth-page">
      <header className="lobby-nav">
        <Link to="/login" className="brand" aria-label="MeetQ">
          <span className="brand-mark" aria-hidden="true">MQ</span>
          MeetQ
        </Link>
      </header>
      <main className="auth-main">
        <section className="card auth-card" aria-labelledby="login-title">
          <div className="card-body">
            <h1 id="login-title" className="card-title">
              {joiningRoom ? "Sign in to join the meeting" : "Sign in to MeetQ"}
            </h1>
            <p className="card-description">
              {joiningRoom
                ? "You'll go straight to the meeting after signing in."
                : "Meetings where everyone speaks their own language."}
            </p>

            {noticeView ? (
              <Alert tone={noticeView.tone}>
                {noticeView.text}
                {notice === "server_unreachable" ? (
                  <>
                    {" "}
                    <button type="button" className="link-button" onClick={() => void refresh()}>
                      Try again
                    </button>
                  </>
                ) : null}
              </Alert>
            ) : null}
            {error ? <Alert tone="danger">{error}</Alert> : null}

            {status === "loading" ? (
              <div className="auth-checking" role="status">
                <Spinner /> Checking your sign-in…
              </div>
            ) : !clientId ? (
              <Alert tone="danger">Google sign-in isn't configured for this build (VITE_GOOGLE_CLIENT_ID is missing).</Alert>
            ) : signingIn ? (
              <Button variant="secondary" size="lg" block loading disabled>
                Signing in…
              </Button>
            ) : (
              <GoogleSignInButton onCredential={(credential) => void handleCredential(credential)} onError={setError} />
            )}

            <p className="auth-footnote">
              MeetQ uses your Google name, email and photo for your account. You can still change the name others see
              before joining a meeting.
            </p>
          </div>
        </section>
      </main>
    </div>
  );
}
