import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { HomePage } from "./pages/HomePage";
import { RoomPage } from "./pages/RoomPage";
import { TestPage } from "./pages/TestPage";
import { LoginPage } from "./pages/LoginPage";
import { MyMeetingsPage } from "./pages/meetings/MyMeetingsPage";
import { MyMeetingDetailPage } from "./pages/meetings/MyMeetingDetailPage";
import { RequireAuth } from "./auth/RequireAuth";
import { Spinner } from "./components/ui/Spinner";

// The admin portal ships as its own chunk; meeting users never download it.
const AdminApp = lazy(() => import("./admin/AdminApp"));

export default function App() {
  const location = useLocation();
  const isAdmin = location.pathname.startsWith("/admin");

  return (
    // Keyed by path so each route gets a short fade-in on navigation (not inside /admin).
    <div className="route-view" key={isAdmin ? "admin" : location.pathname}>
      <Routes location={location}>
        {/* User realm: Google sign-in (auth/). */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<RequireAuth><HomePage /></RequireAuth>} />
        <Route path="/rooms/:roomId" element={<RequireAuth><RoomPage /></RequireAuth>} />
        <Route path="/test" element={<RequireAuth><TestPage /></RequireAuth>} />
        <Route path="/meetings" element={<RequireAuth><MyMeetingsPage /></RequireAuth>} />
        <Route path="/meetings/:roomId" element={<RequireAuth><MyMeetingDetailPage /></RequireAuth>} />
        {/* Admin realm: separate username/password session (admin/auth/). */}
        <Route
          path="/admin/*"
          element={
            <Suspense
              fallback={
                <main className="room-boot" role="status">
                  <Spinner size="lg" />
                </main>
              }
            >
              <AdminApp />
            </Suspense>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
