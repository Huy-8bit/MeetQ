import type { ReactNode } from "react";

interface SettingsDrawerProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}

export function SettingsDrawer({
  open,
  onClose,
  children,
}: SettingsDrawerProps) {
  if (!open) {
    return null;
  }

  return (
    <div className="settings-drawer-layer" role="presentation">
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
            <span>Settings</span>
            <h2 id="settings-drawer-title">Devices</h2>
          </div>
          <button
            className="settings-drawer-close"
            type="button"
            onClick={onClose}
            aria-label="Close settings"
          >
            Close
          </button>
        </header>
        <div className="settings-drawer-content">{children}</div>
      </aside>
    </div>
  );
}
