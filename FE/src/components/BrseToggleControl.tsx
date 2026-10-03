import {
  getBrseModeDescription,
  type BrseRoomMode,
} from "../lib/brseModes";
import { Switch } from "./ui/Switch";

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
  const description = isCaptionOnly ? "Transcript/captions" : getBrseModeDescription(mode);

  return (
    <Switch
      checked={enabled}
      disabled={disabled || pending}
      onChange={onToggle}
      title={`AI relay: ${enabled ? description : "off"}`}
      label={pending ? "Updating…" : isCaptionOnly ? "Captions" : "AI relay"}
    />
  );
}
