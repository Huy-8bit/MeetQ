import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { ApiError } from "../../lib/api";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Field } from "../../components/ui/Field";
import { Spinner } from "../../components/ui/Spinner";
import { useAdminSession } from "../auth/AdminSession";

function loginErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "admin_disabled") return "The admin portal is disabled on this server.";
    if (error.status === 429 || error.code === "too_many_attempts") {
      return "Too many failed attempts. Wait a few minutes and try again.";
    }
    if (error.status === 401 && error.code === "admin_session_not_established") return error.message;
    if (error.status === 401 || error.code === "invalid_credentials") return "Incorrect username or password.";
    if (error.status === 404 || error.status === 501) return "Admin sign-in isn't available on this server yet.";
    return "Sign-in failed. Try again.";
  }
  return "Couldn't reach the admin API.";
}

/** Only return to admin pages after sign-in. */
function safeAdminPath(value: unknown): string {
  if (typeof value !== "string") return "/admin";
  if (!value.startsWith("/admin") || value.startsWith("/admin/login")) return "/admin";
  return value;
}

export function LoginPage() {
  const { status, login, endedReason } = useAdminSession();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const from = safeAdminPath((location.state as { from?: unknown } | null)?.from);

  if (status === "authenticated") {
    return <Navigate to={from} replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!username.trim() || !password) return;
    setSubmitting(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (caught) {
      setError(loginErrorMessage(caught));
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="adm-login">
      <form className="card adm-login-card" onSubmit={(event) => void handleSubmit(event)} noValidate>
        <div className="card-body">
          <p className="brand">
            <span className="brand-mark" aria-hidden="true">MQ</span>
            MeetQ <span className="adm-brand-suffix">Admin</span>
          </p>
          <h1 className="card-title">Sign in to the admin portal</h1>
          <p className="card-description">Operators only. Admin accounts are separate from MeetQ Google accounts.</p>
          {status === "loading" ? (
            <div className="auth-checking" role="status">
              <Spinner /> Checking your session…
            </div>
          ) : null}
          {endedReason ? <Alert tone="info">{endedReason}</Alert> : null}
          <Field label="Username" htmlFor="admin-username">
            <input
              id="admin-username"
              className="input"
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoFocus
              required
            />
          </Field>
          <Field label="Password" htmlFor="admin-password">
            <input
              id="admin-password"
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </Field>
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Button
            type="submit"
            variant="primary"
            size="lg"
            block
            loading={submitting}
            disabled={!username.trim() || !password || status === "loading"}
          >
            {submitting ? "Signing in…" : "Sign in"}
          </Button>
        </div>
      </form>
    </main>
  );
}
