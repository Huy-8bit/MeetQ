import type { AudioDeviceOption } from "../types/livekit";
import { CustomSelect, type CustomSelectOption } from "./CustomSelect";
import { Alert } from "./ui/Alert";
import { Field } from "./ui/Field";
import { Switch } from "./ui/Switch";

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
}: AudioDevicePanelProps) {
  const inputDeviceOptions = buildDeviceOptions(
    audioInputDevices,
    "No microphone devices found",
  );
  const outputDeviceOptions: CustomSelectOption[] = !audioOutputSupported
    ? [{ value: "", label: "System default", disabled: true }]
    : buildDeviceOptions(audioOutputDevices, "No speaker devices found");

  return (
    <section className="drawer-section" aria-labelledby="audio-settings-title">
      <div className="drawer-section-header">
        <h3 className="section-title" id="audio-settings-title">Audio</h3>
      </div>

      <div className="drawer-section-body">
        <div className="settings-row">
          <div>
            <p className="field-label">Microphone</p>
            <p className="field-helper">
              {isMutedByHost && isMicMuted ? "The host muted you." : isMicMuted ? "Muted" : "On"}
            </p>
          </div>
          <Switch
            checked={!isMicMuted}
            onChange={onToggleMic}
            disabled={isTogglingMic}
            label="Microphone"
            hideLabel
          />
        </div>
        {micToggleError ? <Alert tone="danger">{micToggleError}</Alert> : null}

        <Field label="Input device" htmlFor="audio-input-device" error={audioInputError}>
          <CustomSelect
            id="audio-input-device"
            value={selectedAudioInputDeviceId}
            options={inputDeviceOptions}
            disabled={isSwitchingAudioInput || audioInputDevices.length === 0}
            onChange={onSelectAudioInput}
            placeholder={
              audioInputDevices.length === 0 ? "No microphone found" : "Select microphone"
            }
            ariaLabel="Input device"
          />
        </Field>

        <Field
          label="Output device"
          htmlFor="audio-output-device"
          error={audioOutputError}
          helper={audioOutputSupported ? undefined : "This browser can't change the output device."}
        >
          <CustomSelect
            id="audio-output-device"
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
                ? "System default"
                : audioOutputDevices.length === 0
                  ? "No speaker found"
                  : "Select speaker"
            }
            ariaLabel="Output device"
          />
        </Field>
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
