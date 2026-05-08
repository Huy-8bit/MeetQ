import {
  getBrseModeDescription,
  getBrseModeLabel,
  type BrseRoomMode,
} from "../lib/brseModes";

interface BrseToggleControlProps {
  enabled: boolean;
  mode: BrseRoomMode;
  pending?: boolean;
  disabled?: boolean;
  onToggle: (nextEnabled: boolean) => void;
}

export function BrseToggleControl({
  enabled,
  mode,
  pending = false,
  disabled = false,
  onToggle,
}: BrseToggleControlProps) {
  const label = getBrseModeLabel(mode);
  const description = getBrseModeDescription(mode);

  return (
    <button
      className={[
        "brse-toggle-control",
        enabled ? "is-on" : "is-off",
        mode === "text_only" ? "is-text-only" : "",
        mode === "silent_summary" ? "is-summary" : "",
      ].filter(Boolean).join(" ")}
      type="button"
      aria-pressed={enabled}
      disabled={disabled || pending}
      onClick={() => onToggle(!enabled)}
    >
      <span className="brse-toggle-copy">
        <strong>{pending ? "Updating" : label}</strong>
        <span>{description}</span>
      </span>
      <span className="brse-toggle-track" aria-hidden="true">
        <span className="brse-toggle-thumb" />
      </span>
    </button>
  );
}
