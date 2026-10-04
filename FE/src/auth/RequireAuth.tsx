import { useEffect, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Spinner } from "../components/ui/Spinner";
import { useAuth } from "./AuthProvider";
import { loginPathFor } from "./next";

/**
 * Renders user routes only after GET /api/auth/me confirmed a session.
 * Nothing protected is rendered while the check runs; signed-out visitors go
 * to /login with the current path (e.g. a room invite) kept in `next`.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status, ensureChecked } = useAuth();
  const location = useLocation();

  useEffect(() => {
    ensureChecked();
  }, [ensureChecked]);

  if (status === "loading") {
    return <AuthCheckScreen />;
  }
  if (status === "unauthenticated") {
    return <Navigate to={loginPathFor(`${location.pathname}${location.search}${location.hash}`)} replace />;
  }
  return <>{children}</>;
}

export function AuthCheckScreen() {
  return (
    <main className="room-boot" role="status" aria-label="Checking your sign-in">
      <Spinner size="lg" />
    </main>
  );
}
