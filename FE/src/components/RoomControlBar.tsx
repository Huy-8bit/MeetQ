import type { RoomPanelTab } from "./RoomSidePanel";

interface RoomControlBarProps {
  activePanel: RoomPanelTab;
  sidePanelOpen: boolean;
  isMicMuted: boolean;
  isTogglingMic: boolean;
  isMutedByHost: boolean;
  isCameraOff: boolean;
  isTogglingCamera: boolean;
  isScreenSharing: boolean;
  isStartingScreenShare: boolean;
  isStoppingScreenShare: boolean;
  stageFocusActive: boolean;
  isLeaving: boolean;
  onToggleMic: () => void;
  onToggleCamera: () => void;
  onToggleScreenShare: () => void;
  onToggleStageFocus: () => void;
  onOpenPanel: (tab: RoomPanelTab) => void;
  onToggleSidePanel: () => void;
  onOpenSettings: () => void;
  onLeave: () => void;
}

export function RoomControlBar({
  activePanel,
  sidePanelOpen,
  isMicMuted,
  isTogglingMic,
  isMutedByHost,
  isCameraOff,
  isTogglingCamera,
  isScreenSharing,
  isStartingScreenShare,
  isStoppingScreenShare,
  stageFocusActive,
  isLeaving,
  onToggleMic,
  onToggleCamera,
  onToggleScreenShare,
  onToggleStageFocus,
  onOpenPanel,
  onToggleSidePanel,
  onOpenSettings,
  onLeave,
}: RoomControlBarProps) {
  const screenShareBusy = isStartingScreenShare || isStoppingScreenShare;
  const micDisabled = isTogglingMic || (isMutedByHost && isMicMuted);

  return (
    <footer className="room-control-bar">
      {/* Left: media controls */}
      <div className="room-control-group">
        <ControlButton
          active={!isMicMuted}
          muted={isMicMuted}
          disabled={micDisabled}
          onClick={onToggleMic}
          label={isMutedByHost && isMicMuted ? "Muted by host" : isMicMuted ? "Unmute" : "Mute"}
        />
        <ControlButton
          active={!isCameraOff}
          muted={isCameraOff}
          disabled={isTogglingCamera || isLeaving}
          onClick={onToggleCamera}
          label={isCameraOff ? "Start video" : "Stop video"}
        />
        <ControlButton
          active={isScreenSharing}
          disabled={screenShareBusy || isLeaving}
          onClick={onToggleScreenShare}
          label={
            isStartingScreenShare ? "Starting…" :
            isStoppingScreenShare ? "Stopping…" :
            isScreenSharing ? "Stop share" : "Share"
          }
        />
      </div>

      {/* Right side: panel tabs + secondary actions */}
      <div className="room-control-right-cluster">
        {/* Center: panel tabs */}
        <div className="room-control-tabs" aria-label="Open room panel">
          {(["relay", "chat", "summary", "people"] as RoomPanelTab[]).map((tab) => (
            <button
              key={tab}
              className={activePanel === tab && sidePanelOpen ? "panel-shortcut is-active" : "panel-shortcut"}
              type="button"
              onClick={() => onOpenPanel(tab)}
            >
              {formatPanelTabLabel(tab)}
            </button>
          ))}
        </div>

        {/* Right: secondary actions */}
        <div className="room-control-secondary">
          <button
            className={stageFocusActive ? "control-icon-btn control-text-btn is-active" : "control-icon-btn control-text-btn"}
            type="button"
            aria-label={stageFocusActive ? "Exit stage focus" : "Focus stage"}
            title={stageFocusActive ? "Exit stage focus" : "Focus stage"}
            onClick={onToggleStageFocus}
          >
            {stageFocusActive ? "Exit" : "Focus"}
          </button>
          <button
            className="control-icon-btn"
            type="button"
            aria-label={sidePanelOpen ? "Hide panel" : "Show panel"}
            title={sidePanelOpen ? "Hide panel" : "Show panel"}
            onClick={onToggleSidePanel}
          >
            {sidePanelOpen ? "⇥" : "⇤"}
          </button>
          <button
            className="control-icon-btn"
            type="button"
            aria-label="Settings"
            title="Settings"
            onClick={onOpenSettings}
          >
            ⚙
          </button>
          <button
            className="leave-button"
            type="button"
            onClick={onLeave}
            disabled={isLeaving}
          >
            {isLeaving ? "Leaving…" : "Leave"}
          </button>
        </div>
      </div>
    </footer>
  );
}

function formatPanelTabLabel(tab: RoomPanelTab): string {
  if (tab === "relay") return "Relay";
  if (tab === "chat") return "Chat";
  if (tab === "summary") return "Summary";
  return "People";
}

function ControlButton({
  active,
  muted = false,
  disabled = false,
  onClick,
  label,
}: {
  active: boolean;
  muted?: boolean;
  disabled?: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      className={[
        "meeting-control-button",
        active ? "is-live" : "",
        muted ? "is-muted" : "",
      ].filter(Boolean).join(" ")}
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
    >
      <span className="control-btn-label">{label}</span>
    </button>
  );
}
