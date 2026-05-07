import type { AudioDeviceOption } from "../types/livekit";
import { CustomSelect, type CustomSelectOption } from "./CustomSelect";

interface AudioDevicePanelProps {
  isMicMuted: boolean;
  isTogglingMic: boolean;
  micToggleError: string | null;
  isMutedByHost?: boolean;
  onToggleMic: () => void;
  audioInputDevices: AudioDeviceOption[];
  selectedAudioInputDeviceId: string;
  isSwitchingAudioInput: boolean;
  audioInputError: string | null;
  onSelectAudioInput: (deviceId: string) => void;
  audioOutputSupported: boolean;
  audioOutputDevices: AudioDeviceOption[];
  selectedAudioOutputDeviceId: string;
  isSwitchingAudioOutput: boolean;
  audioOutputError: string | null;
  onSelectAudioOutput: (deviceId: string) => void;
  embedded?: boolean;
}

export function AudioDevicePanel({
  isMicMuted,
  isTogglingMic,
  micToggleError,
  isMutedByHost = false,
  onToggleMic,
  audioInputDevices,
  selectedAudioInputDeviceId,
  isSwitchingAudioInput,
  audioInputError,
  onSelectAudioInput,
  audioOutputSupported,
  audioOutputDevices,
  selectedAudioOutputDeviceId,
  isSwitchingAudioOutput,
  audioOutputError,
  onSelectAudioOutput,
  embedded = false,
}: AudioDevicePanelProps) {
  const inputDeviceOptions = buildDeviceOptions(
    audioInputDevices,
    "No microphone devices found",
  );
  const outputDeviceOptions: CustomSelectOption[] = !audioOutputSupported
    ? [{ value: "", label: "Browser does not support output selection", disabled: true }]
    : buildDeviceOptions(audioOutputDevices, "No speaker devices found");

  return (
    <section className={embedded ? "audio-settings-panel panel-section" : "panel audio-settings-panel"}>
      <div className="panel-header">
        <div>
          <h3>Audio Settings</h3>
          <p>Control microphone and playback devices for this room session.</p>
        </div>
      </div>

      <div className="audio-settings-grid">
        <div className="audio-setting-row">
          <span className="audio-setting-label">Microphone</span>
          <button
            className={isMicMuted ? "button-secondary" : "button-primary"}
            onClick={onToggleMic}
            disabled={isTogglingMic || (isMutedByHost && isMicMuted)}
          >
            {isTogglingMic
              ? "Updating..."
              : isMutedByHost && isMicMuted
                ? "Muted by host"
                : isMicMuted
                  ? "Unmute mic"
                  : "Mute mic"}
          </button>
        </div>

        {micToggleError ? (
          <div className="inline-error audio-setting-error">{micToggleError}</div>
        ) : null}

        <label className="field audio-setting-field">
          <span>Input Device</span>
          <CustomSelect
            className="audio-device-select"
            value={selectedAudioInputDeviceId}
            options={inputDeviceOptions}
            disabled={isSwitchingAudioInput || audioInputDevices.length === 0}
            onChange={onSelectAudioInput}
            placeholder={
              audioInputDevices.length === 0 ? "No microphone devices found" : "Select microphone"
            }
            ariaLabel="Input device"
          />
        </label>

        {audioInputError ? (
          <div className="inline-error audio-setting-error">{audioInputError}</div>
        ) : null}

        <label className="field audio-setting-field">
          <span>Output Device</span>
          <CustomSelect
            className="audio-device-select"
            value={selectedAudioOutputDeviceId}
            options={outputDeviceOptions}
            disabled={
              !audioOutputSupported
              || isSwitchingAudioOutput
              || audioOutputDevices.length === 0
            }
            onChange={onSelectAudioOutput}
            placeholder={
              !audioOutputSupported
                ? "Browser does not support output selection"
                : audioOutputDevices.length === 0
                  ? "No speaker devices found"
                  : "Select speaker"
            }
            ariaLabel="Output device"
          />
        </label>

        {!audioOutputSupported ? (
          <div className="audio-setting-hint">
            This browser does not support changing audio output device.
          </div>
        ) : null}

        {audioOutputError ? (
          <div className="inline-error audio-setting-error">{audioOutputError}</div>
        ) : null}
      </div>
    </section>
  );
}

function buildDeviceOptions(
  devices: AudioDeviceOption[],
  emptyLabel: string,
): CustomSelectOption[] {
  if (devices.length === 0) {
    return [{ value: "", label: emptyLabel, disabled: true }];
  }

  return devices.map((device) => ({
    value: device.deviceId,
    label: device.label,
  }));
}
