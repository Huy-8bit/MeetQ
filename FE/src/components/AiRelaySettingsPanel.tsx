import { getBrseModeDescription, type BrseRoomMode } from "../lib/brseModes";
import type { BrseOutputMode } from "../types/api";
import { RelayModeControl } from "./RelayModeControl";
import { Alert } from "./ui/Alert";
import { Field } from "./ui/Field";
import { Switch } from "./ui/Switch";

interface AiRelaySettingsPanelProps {
  brseEnabled: boolean;
  brseRoomMode: BrseRoomMode;
  languageCount: number;
  isTogglingBrse: boolean;
  canToggleBrse: boolean;
  onToggleBrse: (nextEnabled: boolean) => void;
  relayMode: BrseOutputMode;
  relayModes: BrseOutputMode[];
  isUpdatingRelayMode: boolean;
  canChangeRelayMode: boolean;
  onChangeRelayMode: (mode: BrseOutputMode) => void;
  relayModeError: string | null;
}

/** Settings section bound to the same room state as the header controls. */
export function AiRelaySettingsPanel({
  brseEnabled,
  brseRoomMode,
  languageCount,
  isTogglingBrse,
  canToggleBrse,
  onToggleBrse,
  relayMode,
  relayModes,
  isUpdatingRelayMode,
  canChangeRelayMode,
  onChangeRelayMode,
  relayModeError,
}: AiRelaySettingsPanelProps) {
  const fixedModeNote =
    languageCount === 1
      ? "Single-language rooms show captions. AI voice isn't available."
      : languageCount > 2
        ? "Rooms with 3 or more languages use text relay. AI voice needs exactly two languages."
        : null;

  return (
    <section className="drawer-section" aria-labelledby="ai-relay-settings-title">
      <div className="drawer-section-header">
        <h3 className="section-title" id="ai-relay-settings-title">AI relay</h3>
      </div>
      <div className="drawer-section-body">
        <div className="settings-row">
          <div>
            <p className="field-label">Enabled</p>
            <p className="field-helper">
              {isTogglingBrse ? "Updating…" : brseEnabled ? getBrseModeDescription(brseRoomMode) : "Off for everyone in this room"}
            </p>
          </div>
          <Switch
            checked={brseEnabled}
            onChange={onToggleBrse}
            disabled={!canToggleBrse}
            label="AI relay"
            hideLabel
          />
        </div>
        {relayModes.length > 1 ? (
          <Field
            label="Mode"
            htmlFor="settings-relay-mode"
            helper={
              brseEnabled
                ? "Applies to everyone in the room."
                : "AI relay is off. This mode is used when it's turned back on."
            }
          >
            <RelayModeControl
              id="settings-relay-mode"
              size="standard"
              mode={relayMode}
              modes={relayModes}
              pending={isUpdatingRelayMode}
              disabled={!canChangeRelayMode}
              onChange={onChangeRelayMode}
            />
          </Field>
        ) : fixedModeNote ? (
          <p className="field-helper">{fixedModeNote}</p>
        ) : null}
        {relayModeError ? <Alert tone="danger">{relayModeError}</Alert> : null}
      </div>
    </section>
  );
}
