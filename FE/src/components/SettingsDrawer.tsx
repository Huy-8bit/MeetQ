import type { ReactNode } from "react";
import { useDrawerRevealMotion } from "../lib/motion";
import { MotionButton } from "./MotionButton";

interface SettingsDrawerProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  eyebrow?: string;
  title?: string;
}

export function SettingsDrawer({
  open,
  onClose,
  children,
  eyebrow = "Settings",
  title = "Devices",
}: SettingsDrawerProps) {
  const drawerMotionRef = useDrawerRevealMotion<HTMLDivElement>(open);

  if (!open) {
    return null;
  }

  return (
    <div className="settings-drawer-layer" role="presentation" ref={drawerMotionRef}>
      <button
        className="settings-drawer-backdrop"
        type="button"
        aria-label="Close settings"
        onClick={onClose}
      />
      <aside
        className="settings-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-drawer-title"
      >
        <header className="settings-drawer-header">
          <div>
            <span>{eyebrow}</span>
            <h2 id="settings-drawer-title">{title}</h2>
          </div>
          <MotionButton
            className="settings-drawer-close"
            type="button"
            onClick={onClose}
            aria-label="Close settings"
          >
            Close
          </MotionButton>
        </header>
        <div className="settings-drawer-content">{children}</div>
      </aside>
    </div>
  );
}
