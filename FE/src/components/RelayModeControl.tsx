import { RELAY_MODE_OPTIONS } from "../lib/brseModes";
import type { BrseOutputMode } from "../types/api";
import { CustomSelect, type CustomSelectOption } from "./CustomSelect";

interface RelayModeControlProps {
  /** Current room mode from the server. */
  mode: BrseOutputMode;
  /** Modes this room allows; empty means the room has no choice (control is hidden). */
  modes: BrseOutputMode[];
  pending?: boolean;
  disabled?: boolean;
  onChange: (mode: BrseOutputMode) => void;
  id?: string;
  size?: "standard" | "compact";
}

/**
 * Room-level AI relay mode (Voice + Text / Text Only). Shown only for rooms with a
 * real choice (exactly two languages). Independent of the AI relay on/off switch:
 * changing it while AI is off only stores the mode used when AI is turned on.
 */
export function RelayModeControl({
  mode,
  modes,
  pending = false,
  disabled = false,
  onChange,
  id,
  size = "compact",
}: RelayModeControlProps) {
  if (modes.length < 2) {
    return null;
  }

  const options: Array<CustomSelectOption<BrseOutputMode>> = RELAY_MODE_OPTIONS.filter((option) =>
    modes.includes(option.value),
  ).map((option) => ({ value: option.value, label: option.label, helper: option.description }));

  return (
    <CustomSelect<BrseOutputMode | "">
      id={id}
      size={size}
      ariaLabel="AI relay mode"
      // While the server applies the change, show "Updating…" instead of guessing the result.
      value={pending ? "" : mode}
      placeholder="Updating…"
      options={options}
      disabled={disabled || pending}
      onChange={(next) => {
        if (next && next !== mode) {
          onChange(next);
        }
      }}
    />
  );
}
