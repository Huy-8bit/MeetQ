import {
  getBrseModeDescription,
  getBrseModeLabel,
  type BrseRoomMode,
} from "../lib/brseModes";
import { MotionButton } from "./MotionButton";

interface BrseToggleControlProps {
  enabled: boolean;
  mode: BrseRoomMode;
  languageCount?: number;
  pending?: boolean;
  disabled?: boolean;
  onToggle: (nextEnabled: boolean) => void;
}

export function BrseToggleControl({
  enabled,
  mode,
  languageCount = 0,
  pending = false,
  disabled = false,
  onToggle,
}: BrseToggleControlProps) {
  const isCaptionOnly = enabled && mode === "text_only" && languageCount === 1;
  const label = isCaptionOnly ? "Captions" : getBrseModeLabel(mode);
  const description = isCaptionOnly ? "Transcript/captions" : getBrseModeDescription(mode);

  return (
    <MotionButton
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
    </MotionButton>
  );
}
