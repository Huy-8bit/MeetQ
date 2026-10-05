import {
  LogOut,
  Mic,
  MicOff,
  MonitorUp,
  PanelRight,
  Settings,
  Video,
  VideoOff,
} from "lucide-react";
import type { ReactNode } from "react";
import { Spinner } from "./ui/Spinner";

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
  /** False when the browser has no getDisplayMedia (phones, tablets). */
  canShareScreen?: boolean;
  isLeaving: boolean;
  onToggleMic: () => void;
  onToggleCamera: () => void;
  onToggleScreenShare: () => void;
  onToggleSidePanel: () => void;
  onOpenSettings: () => void;
  onLeave: () => void;
  /** Record button (shown when recording is available on the server). */
  recordControl?: ReactNode;
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
  canShareScreen = true,
  isLeaving,
  onToggleMic,
  onToggleCamera,
  onToggleScreenShare,
  onToggleSidePanel,
  onOpenSettings,
  onLeave,
  recordControl,
}: RoomControlBarProps) {
  const screenShareBusy = isStartingScreenShare || isStoppingScreenShare;
  const micDisabled = isTogglingMic || (isMutedByHost && isMicMuted);

  return (
    <div className="control-bar" role="toolbar" aria-label="Meeting controls">
      <div className="control-bar-group">
        <ControlButton
          state={isMicMuted ? "off" : "on"}
          busy={isTogglingMic}
          disabled={micDisabled}
          onClick={onToggleMic}
          label={isMutedByHost && isMicMuted ? "Muted by host" : isMicMuted ? "Unmute" : "Mute"}
          icon={isMicMuted ? <MicOff size={18} /> : <Mic size={18} />}
        />
        <ControlButton
          state={isCameraOff ? "off" : "on"}
          busy={isTogglingCamera}
          disabled={isTogglingCamera || isLeaving}
          onClick={onToggleCamera}
          label={isCameraOff ? "Start video" : "Stop video"}
          icon={isCameraOff ? <VideoOff size={18} /> : <Video size={18} />}
        />
        <ControlButton
          state={isScreenSharing ? "active" : "on"}
          busy={screenShareBusy}
          disabled={screenShareBusy || isLeaving}
          onClick={onToggleScreenShare}
          label={
            isStartingScreenShare ? "Starting…" :
            isStoppingScreenShare ? "Stopping…" :
            isScreenSharing ? "Stop sharing" : "Share screen"
          }
          icon={<MonitorUp size={18} />}
          unavailableReason={
            canShareScreen || isScreenSharing ? undefined : "Screen sharing isn't supported on this device."
          }
        />
        {recordControl}
      </div>

      <div className="control-bar-group control-bar-end">
        <button
          className="control-btn control-btn--quiet"
          type="button"
          aria-pressed={sidePanelOpen}
          aria-label={sidePanelOpen ? "Hide side panel" : "Show side panel"}
          title={sidePanelOpen ? "Hide side panel" : "Show side panel"}
          onClick={onToggleSidePanel}
        >
          <PanelRight size={18} aria-hidden="true" />
        </button>
        <button
          className="control-btn control-btn--quiet"
          type="button"
          aria-label="Settings"
          title="Settings"
          onClick={onOpenSettings}
        >
          <Settings size={18} aria-hidden="true" />
        </button>
        <button
          className="control-btn control-btn--leave"
          type="button"
          onClick={onLeave}
          disabled={isLeaving}
          aria-label={isLeaving ? "Leaving…" : "Leave meeting"}
        >
          {isLeaving ? <Spinner /> : <LogOut size={18} aria-hidden="true" />}
          <span className="control-btn-label">{isLeaving ? "Leaving…" : "Leave"}</span>
        </button>
      </div>
    </div>
  );
}

function ControlButton({
  state,
  busy = false,
  disabled = false,
  onClick,
  label,
  icon,
  unavailableReason,
}: {
  /** "off" = muted/camera off, "active" = presenting. Label text always states it too. */
  state: "on" | "off" | "active";
  busy?: boolean;
  disabled?: boolean;
  onClick: () => void;
  label: string;
  icon: ReactNode;
  /**
   * The control can't work here. Uses aria-disabled (not `disabled`) so the
   * tooltip explaining why still shows on hover/focus.
   */
  unavailableReason?: string;
}) {
  const unavailable = !!unavailableReason;
  return (
    <button
      className={`control-btn is-${state}${unavailable ? " is-unavailable" : ""}`}
      type="button"
      onClick={unavailable ? undefined : onClick}
      disabled={disabled}
      aria-disabled={unavailable || undefined}
      aria-label={unavailable ? `${label} (${unavailableReason})` : label}
      aria-busy={busy || undefined}
      title={unavailableReason ?? label}
    >
      <span className="control-btn-icon" aria-hidden="true">{busy ? <Spinner /> : icon}</span>
      <span className="control-btn-label">{label}</span>
    </button>
  );
}
