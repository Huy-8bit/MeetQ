import {
  DoorOpen,
  Mic,
  MicOff,
  MonitorUp,
  PanelRightClose,
  PanelRightOpen,
  Settings,
  Video,
  VideoOff,
} from "lucide-react";
import type { ReactNode } from "react";
import { MotionButton } from "./MotionButton";

interface RoomControlBarProps {
  sidePanelOpen: boolean;
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
  onToggleSidePanel: () => void;
  onOpenSettings: () => void;
  onLeave: () => void;
}

export function RoomControlBar({
  sidePanelOpen,
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
  onToggleSidePanel,
  onOpenSettings,
  onLeave,
}: RoomControlBarProps) {
  const screenShareBusy = isStartingScreenShare || isStoppingScreenShare;
  const micDisabled = isTogglingMic || (isMutedByHost && isMicMuted);

  return (
    <footer className="room-control-bar">
      <div className="room-control-group room-control-media">
        <ControlButton
          active={!isMicMuted}
          muted={isMicMuted}
          disabled={micDisabled}
          onClick={onToggleMic}
          label={isMutedByHost && isMicMuted ? "Muted by host" : isMicMuted ? "Unmute" : "Mute"}
          icon={isMicMuted ? <MicOff size={18} /> : <Mic size={18} />}
        />
        <ControlButton
          active={!isCameraOff}
          muted={isCameraOff}
          disabled={isTogglingCamera || isLeaving}
          onClick={onToggleCamera}
          label={isCameraOff ? "Start video" : "Stop video"}
          icon={isCameraOff ? <VideoOff size={18} /> : <Video size={18} />}
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
          icon={<MonitorUp size={18} />}
        />
      </div>

      <div className="room-control-secondary">
        <MotionButton
          className={sidePanelOpen ? "control-icon-btn control-text-btn context-toggle-btn is-active" : "control-icon-btn control-text-btn context-toggle-btn"}
          type="button"
          aria-label={sidePanelOpen ? "Hide context panel" : "Show context panel"}
          title={sidePanelOpen ? "Hide context panel" : "Show context panel"}
          onClick={onToggleSidePanel}
        >
          {sidePanelOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
          <span>{sidePanelOpen ? "Hide" : "Context"}</span>
        </MotionButton>
        <MotionButton
          className="control-icon-btn"
          type="button"
          aria-label="Settings"
          title="Settings"
          onClick={onOpenSettings}
        >
          <Settings size={18} />
        </MotionButton>
        <MotionButton
          className="leave-button"
          type="button"
          onClick={onLeave}
          disabled={isLeaving}
        >
          <DoorOpen size={17} />
          {isLeaving ? "Leaving…" : "Leave"}
        </MotionButton>
      </div>
    </footer>
  );
}

function ControlButton({
  active,
  muted = false,
  disabled = false,
  onClick,
  label,
  icon,
}: {
  active: boolean;
  muted?: boolean;
  disabled?: boolean;
  onClick: () => void;
  label: string;
  icon: ReactNode;
}) {
  return (
    <MotionButton
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
      <span className="control-btn-icon" aria-hidden="true">{icon}</span>
      <span className="control-btn-label">{label}</span>
    </MotionButton>
  );
}
