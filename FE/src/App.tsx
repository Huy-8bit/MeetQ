import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { HomePage } from "./pages/HomePage";
import { RoomPage } from "./pages/RoomPage";
import { TestPage } from "./pages/TestPage";

export default function App() {
  const location = useLocation();

  return (
    // Keyed by path so each route gets a short fade-in on navigation.
    <div className="route-view" key={location.pathname}>
      <Routes location={location}>
        <Route path="/" element={<HomePage />} />
        <Route path="/rooms/:roomId" element={<RoomPage />} />
        <Route path="/test" element={<TestPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
