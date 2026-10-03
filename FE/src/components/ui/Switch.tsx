import type { ReactNode } from "react";

interface SwitchProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: ReactNode;
  /** Hide the visible label (still announced). */
  hideLabel?: boolean;
  disabled?: boolean;
  title?: string;
}

export function Switch({ checked, onChange, label, hideLabel = false, disabled = false, title }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      className="switch"
      aria-checked={checked}
      disabled={disabled}
      title={title}
      onClick={() => onChange(!checked)}
    >
      <span className="switch-track" aria-hidden="true">
        <span className="switch-thumb" />
      </span>
      <span className={hideLabel ? "sr-only" : undefined}>{label}</span>
    </button>
  );
}
