import type { RoomPanelTab } from "./RoomSidePanel";

interface RoomControlBarProps {
  activePanel: RoomPanelTab;
  isMicMuted: boolean;
  isTogglingMic: boolean;
  isMutedByHost: boolean;
  isCameraOff: boolean;
  isTogglingCamera: boolean;
  isScreenSharing: boolean;
  isStartingScreenShare: boolean;
  isStoppingScreenShare: boolean;
  isLeaving: boolean;
  onToggleMic: () => void;
  onToggleCamera: () => void;
  onToggleScreenShare: () => void;
  onOpenPanel: (tab: RoomPanelTab) => void;
  onOpenSettings: () => void;
  onLeave: () => void;
}

export function RoomControlBar({
  activePanel,
  isMicMuted,
  isTogglingMic,
  isMutedByHost,
  isCameraOff,
  isTogglingCamera,
  isScreenSharing,
  isStartingScreenShare,
  isStoppingScreenShare,
  isLeaving,
  onToggleMic,
  onToggleCamera,
  onToggleScreenShare,
  onOpenPanel,
  onOpenSettings,
  onLeave,
}: RoomControlBarProps) {
  const screenShareBusy = isStartingScreenShare || isStoppingScreenShare;

  return (
    <footer className="room-control-bar">
      <div className="room-control-group">
        <button
          className={isMicMuted ? "meeting-control-button is-muted" : "meeting-control-button is-live"}
          type="button"
          onClick={onToggleMic}
          disabled={isTogglingMic || (isMutedByHost && isMicMuted)}
        >
          <span className="control-icon" aria-hidden="true">M</span>
          {isTogglingMic
            ? "Updating mic"
            : isMutedByHost && isMicMuted
              ? "Muted by host"
              : isMicMuted
                ? "Unmute"
                : "Mute"}
        </button>

        <button
          className={isCameraOff ? "meeting-control-button is-muted" : "meeting-control-button is-live"}
          type="button"
          onClick={onToggleCamera}
          disabled={isTogglingCamera || isLeaving}
        >
          <span className="control-icon" aria-hidden="true">C</span>
          {isTogglingCamera
            ? "Updating camera"
            : isCameraOff
              ? "Start video"
              : "Stop video"}
        </button>

        <button
          className={isScreenSharing ? "meeting-control-button is-sharing" : "meeting-control-button"}
          type="button"
          onClick={onToggleScreenShare}
          disabled={screenShareBusy || isLeaving}
        >
          <span className="control-icon" aria-hidden="true">S</span>
          {isStartingScreenShare
            ? "Requesting share"
            : isStoppingScreenShare
              ? "Stopping share"
              : isScreenSharing
                ? "Stop share"
                : "Share screen"}
        </button>
      </div>

      <div className="room-control-tabs" aria-label="Open room panel">
        {(["relay", "chat", "people"] as RoomPanelTab[]).map((tab) => (
          <button
            className={activePanel === tab ? "panel-shortcut is-active" : "panel-shortcut"}
            key={tab}
            type="button"
            onClick={() => onOpenPanel(tab)}
          >
            {tab === "relay"
              ? "Relay"
              : tab === "people"
                ? "People"
                : tab[0].toUpperCase() + tab.slice(1)}
          </button>
        ))}
        <button
          className="panel-shortcut panel-shortcut-settings"
          type="button"
          onClick={onOpenSettings}
          aria-label="Open settings"
        >
          <span className="settings-gear" aria-hidden="true">⚙</span>
          <span>Settings</span>
        </button>
        <button
          className="meeting-control-button leave-control-button"
          type="button"
          onClick={onLeave}
          disabled={isLeaving}
        >
          {isLeaving ? "Leaving" : "Leave"}
        </button>
      </div>
    </footer>
  );
}
