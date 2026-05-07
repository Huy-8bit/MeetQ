import type { GatewayConnectionState } from "../types/livekit";
import type { Language, MeetingLanguage } from "../types/api";
import { formatMeetingLanguageBridge, getLanguageLabel } from "../lib/languages";
import { useRoomExpiry } from "../features/room/useRoomExpiry";
import { BrseToggleControl } from "./BrseToggleControl";
import { ConnectionBadge } from "./ConnectionBadge";
import { CustomSelect, type CustomSelectOption } from "./CustomSelect";

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
  const selectOptions: Array<CustomSelectOption<Language>> = languageOptions.map((item) => ({
    value: item,
    label: getLanguageLabel(item),
  }));

  const { remainingLabel, isExpired } = useRoomExpiry(expiresAt);

  return (
    <header className="room-topbar">
      {/* Left: identity */}
      <div className="room-topbar-identity">
        <div className="room-brand-mark">MQ</div>
        <div className="room-topbar-meta">
          <span className="room-topbar-name">{displayName || "Meeting"}</span>
          <div className="room-topbar-sub">
            <span>{roomId}</span>
            <span>·</span>
            <span>{formatMeetingLanguageBridge(meetingLanguages)}</span>
            <span>·</span>
            <span>{participantCount}p</span>
            {remainingLabel ? (
              <>
                <span>·</span>
                <span className={isExpired ? "topbar-timer expired" : "topbar-timer"}>
                  {isExpired ? "Ended" : remainingLabel}
                </span>
              </>
            ) : null}
          </div>
        </div>
      </div>

      {/* Right: controls */}
      <div className="room-topbar-controls">
        <CustomSelect
          className="topbar-lang-select"
          value={currentLanguage}
          options={selectOptions}
          disabled={meetingLanguages.length !== 2}
          onChange={onChangeLanguage}
          ariaLabel="Your language"
          size="compact"
        />

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
