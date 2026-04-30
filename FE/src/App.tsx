import { Navigate, Route, Routes } from "react-router-dom";
import { HomePage } from "./pages/HomePage";
import { RoomPage } from "./pages/RoomPage";
import { TestPage } from "./pages/TestPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/rooms/:roomId" element={<RoomPage />} />
      <Route path="/test" element={<TestPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
