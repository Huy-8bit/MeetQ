import type { AudioDeviceOption } from "../types/livekit";

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
          <select
            value={selectedAudioInputDeviceId}
            disabled={isSwitchingAudioInput || audioInputDevices.length === 0}
            onChange={(event) => onSelectAudioInput(event.target.value)}
          >
            {audioInputDevices.length === 0 ? (
              <option value="">No microphone devices found</option>
            ) : null}
            {audioInputDevices.map((device) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label}
              </option>
            ))}
          </select>
        </label>

        {audioInputError ? (
          <div className="inline-error audio-setting-error">{audioInputError}</div>
        ) : null}

        <label className="field audio-setting-field">
          <span>Output Device</span>
          <select
            value={selectedAudioOutputDeviceId}
            disabled={
              !audioOutputSupported
              || isSwitchingAudioOutput
              || audioOutputDevices.length === 0
            }
            onChange={(event) => onSelectAudioOutput(event.target.value)}
          >
            {!audioOutputSupported ? (
              <option value="">Browser does not support output selection</option>
            ) : null}
            {audioOutputSupported && audioOutputDevices.length === 0 ? (
              <option value="">No speaker devices found</option>
            ) : null}
            {audioOutputDevices.map((device) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label}
              </option>
            ))}
          </select>
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
