import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Button } from "./Button";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "primary" | "danger";
  /** The user must type this exact text before confirming (destructive actions). */
  requireText?: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Modal confirmation. Esc and the backdrop cancel; focus returns to the opener. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "primary",
  requireText,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId();
  const bodyId = useId();
  const inputId = useId();
  const firstFocusRef = useRef<HTMLButtonElement | HTMLInputElement | null>(null);
  const onCancelRef = useRef(onCancel);
  onCancelRef.current = onCancel;
  const [typed, setTyped] = useState("");

  useEffect(() => {
    if (!open) return;
    setTyped("");
    const previouslyFocused = document.activeElement as HTMLElement | null;
    firstFocusRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancelRef.current();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus?.();
    };
  }, [open]);

  if (!open) return null;
  const confirmDisabled = busy || (requireText !== undefined && typed !== requireText);

  return (
    <div className="dialog-layer">
      <div className="dialog-backdrop" onClick={() => !busy && onCancel()} aria-hidden="true" />
      <div className="dialog card" role="alertdialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={bodyId}>
        <div className="card-body dialog-body">
          <h2 className="card-title" id={titleId}>
            {title}
          </h2>
          <div className="dialog-text" id={bodyId}>
            {children}
          </div>
          {requireText !== undefined ? (
            <div className="field">
              <label className="field-label" htmlFor={inputId}>
                Type {requireText} to confirm
              </label>
              <input
                id={inputId}
                ref={(node) => {
                  firstFocusRef.current = node;
                }}
                className="input"
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                autoComplete="off"
                spellCheck={false}
              />
            </div>
          ) : null}
          <div className="dialog-actions">
            <Button
              ref={(node) => {
                if (requireText === undefined) firstFocusRef.current = node;
              }}
              variant="secondary"
              onClick={onCancel}
              disabled={busy}
            >
              {cancelLabel}
            </Button>
            <Button variant={tone === "danger" ? "danger" : "primary"} onClick={onConfirm} disabled={confirmDisabled} loading={busy}>
              {confirmLabel}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
