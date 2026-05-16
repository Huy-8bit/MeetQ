import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { HomePage } from "./pages/HomePage";
import { RoomPage } from "./pages/RoomPage";
import { TestPage } from "./pages/TestPage";

export default function App() {
  const location = useLocation();
  const shouldReduceMotion = useReducedMotion();

  return (
    <div className="app-route-frame">
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={location.pathname}
          className="app-route-view"
          initial={shouldReduceMotion ? { opacity: 0.96 } : { opacity: 0, y: 8, scale: 0.995 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={shouldReduceMotion ? { opacity: 0.96 } : { opacity: 0, y: -4 }}
          transition={{
            duration: shouldReduceMotion ? 0.08 : 0.22,
            ease: [0.22, 1, 0.36, 1],
          }}
        >
          <Routes location={location}>
            <Route path="/" element={<HomePage />} />
            <Route path="/rooms/:roomId" element={<RoomPage />} />
            <Route path="/test" element={<TestPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
