import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Spinner } from "../components/ui/Spinner";
import "../styles/admin.css";
import { AdminSessionProvider, useAdminSession } from "./auth/AdminSession";
import { AdminLayout } from "./components/AdminLayout";
import { AiRelayPage } from "./pages/AiRelayPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { IssueDetailPage, IssuesPage } from "./pages/IssuesPage";
import { LiveRoomDetailPage } from "./pages/LiveRoomDetailPage";
import { LiveRoomsPage } from "./pages/LiveRoomsPage";
import { LoginPage } from "./pages/LoginPage";
import { MeetingDetailPage } from "./pages/MeetingDetailPage";
import { MeetingsPage } from "./pages/MeetingsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import { RecordingsPage } from "./pages/RecordingsPage";
import { ArchiveDetailPage } from "./pages/ArchiveDetailPage";

function RequireAdmin({ children }: { children: ReactNode }) {
  const { status } = useAdminSession();
  const location = useLocation();
  if (status === "loading") {
    return (
      <main className="adm-login" role="status" aria-label="Checking admin session">
        <Spinner size="lg" />
      </main>
    );
  }
  if (status !== "authenticated") {
    return <Navigate to="/admin/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }
  return <>{children}</>;
}

/** Routes under /admin/*. Loaded lazily so the meeting app bundle stays unchanged. */
export function AdminRoutes() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route
        element={
          <RequireAdmin>
            <AdminLayout />
          </RequireAdmin>
        }
      >
        <Route index element={<OverviewPage />} />
        <Route path="live-rooms" element={<LiveRoomsPage />} />
        <Route path="live-rooms/:roomId" element={<LiveRoomDetailPage />} />
        <Route path="meetings" element={<MeetingsPage />} />
        <Route path="meetings/:roomId" element={<MeetingDetailPage />} />
        <Route path="recordings" element={<RecordingsPage />} />
        <Route path="recordings/:archiveId" element={<ArchiveDetailPage />} />
        <Route path="ai-relay" element={<AiRelayPage />} />
        <Route path="issues" element={<IssuesPage />} />
        <Route path="issues/:code" element={<IssueDetailPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Route>
    </Routes>
  );
}

export default function AdminApp() {
  return (
    <AdminSessionProvider>
      <AdminRoutes />
    </AdminSessionProvider>
  );
}
