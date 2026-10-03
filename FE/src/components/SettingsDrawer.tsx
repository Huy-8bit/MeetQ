import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "./ui/Button";

interface SettingsDrawerProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  title?: string;
}

/** Right-side modal drawer. Closes on Esc / backdrop; restores focus on close. */
export function SettingsDrawer({ open, onClose, children, title = "Settings" }: SettingsDrawerProps) {
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) {
      return;
    }

    const previouslyFocused = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onCloseRef.current();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus?.();
    };
  }, [open]);

  if (!open) {
    return null;
  }

  return (
    <div className="drawer-layer">
      <button className="drawer-backdrop" type="button" tabIndex={-1} aria-label="Close settings" onClick={onClose} />
      <div className="drawer" role="dialog" aria-modal="true" aria-labelledby="settings-drawer-title">
        <div className="drawer-header">
          <h2 className="drawer-title" id="settings-drawer-title">
            {title}
          </h2>
          <Button ref={closeRef} variant="ghost" iconOnly icon={<X size={18} />} aria-label="Close settings" onClick={onClose} />
        </div>
        <div className="drawer-body">{children}</div>
      </div>
    </div>
  );
}
