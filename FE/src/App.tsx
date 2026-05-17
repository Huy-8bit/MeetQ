import { AnimatePresence } from "motion/react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { PageTransition, TransitionOverlay } from "./components/PageTransition";
import { HomePage } from "./pages/HomePage";
import { RoomPage } from "./pages/RoomPage";
import { TestPage } from "./pages/TestPage";

export default function App() {
  const location = useLocation();
  const routeTransitionKey = `${location.pathname}${location.search}`;

  return (
    <div className="app-route-frame">
      <div className="route-ambient-field" aria-hidden="true" />
      <AnimatePresence mode="wait" initial={false}>
        <PageTransition key={routeTransitionKey} routeKey={routeTransitionKey}>
          <Routes location={location}>
            <Route path="/" element={<HomePage />} />
            <Route path="/rooms/:roomId" element={<RoomPage />} />
            <Route path="/test" element={<TestPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </PageTransition>
      </AnimatePresence>
      <TransitionOverlay transitionKey={routeTransitionKey} />
    </div>
  );
}
