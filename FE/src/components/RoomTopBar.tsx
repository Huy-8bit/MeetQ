import type { GatewayConnectionState } from "../types/livekit";
import type { Language, MeetingLanguage } from "../types/api";
import {
  formatMeetingLanguageBridge,
  getLanguageLabel,
} from "../lib/languages";
import { useRoomExpiry } from "../features/room/useRoomExpiry";
import { BrseToggleControl } from "./BrseToggleControl";
import { ConnectionBadge } from "./ConnectionBadge";

interface RoomTopBarProps {
  roomId: string;
  displayName: string;
  meetingLanguages: MeetingLanguage[];
  currentLanguage: Language;
  participantCount: number;
  expiresAt: string | null | undefined;
  connectionState: GatewayConnectionState;
  brseEnabled: boolean;
  isTogglingBrse: boolean;
  brseToggleError: string | null;
  canToggleBrse: boolean;
  onChangeLanguage: (language: Language) => void;
  onToggleBrse: (nextEnabled: boolean) => void;
}

export function RoomTopBar({
  roomId,
  displayName,
  meetingLanguages,
  currentLanguage,
  participantCount,
  expiresAt,
  connectionState,
  brseEnabled,
  isTogglingBrse,
  brseToggleError,
  canToggleBrse,
  onChangeLanguage,
  onToggleBrse,
}: RoomTopBarProps) {
  const languageOptions =
    meetingLanguages.length === 2 ? meetingLanguages : [currentLanguage];

  const { remainingLabel, isExpired } = useRoomExpiry(expiresAt);

  return (
    <header className="room-topbar">
      <div className="room-topbar-main">
        <div className="room-brand-mark">MQ</div>
        <div className="room-title-block">
          <div className="room-title-row">
            <h1>{displayName || "Meeting Room"}</h1>
            <span className={brseEnabled ? "mode-chip mode-chip-on" : "mode-chip"}>
              {brseEnabled ? "BRSE relay" : "Normal mode"}
            </span>
          </div>
          <div className="room-meta-line">
            <span>{roomId}</span>
            <span>{formatMeetingLanguageBridge(meetingLanguages)}</span>
            <span>{participantCount} participant{participantCount === 1 ? "" : "s"}</span>
            {remainingLabel ? (
              <span className={isExpired ? "room-timer-chip room-timer-chip-expired" : "room-timer-chip"}>
                {isExpired ? "Meeting ended" : `${remainingLabel} left`}
              </span>
            ) : null}
          </div>
        </div>
      </div>

      <div className="room-topbar-controls">
        <label className="room-language-select">
          <span>Your language</span>
          <select
            value={currentLanguage}
            disabled={meetingLanguages.length !== 2}
            onChange={(event) => onChangeLanguage(event.target.value as Language)}
          >
            {languageOptions.map((item) => (
              <option key={item} value={item}>
                {getLanguageLabel(item)}
              </option>
            ))}
          </select>
        </label>

        <ConnectionBadge state={connectionState} />

        <BrseToggleControl
          enabled={brseEnabled}
          pending={isTogglingBrse}
          disabled={!canToggleBrse}
          onToggle={onToggleBrse}
        />
      </div>

      {brseToggleError ? (
        <div className="room-topbar-error">{brseToggleError}</div>
      ) : null}
    </header>
  );
}
