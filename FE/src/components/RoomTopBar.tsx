import type { ReactNode } from "react";
import { Clock, Lock, Users } from "lucide-react";
import type { GatewayConnectionState } from "../types/livekit";
import type { BrseOutputMode, Language, MeetingLanguage } from "../types/api";
import { formatMeetingLanguageBridge, getLanguageLabel } from "../lib/languages";
import type { BrseRoomMode } from "../lib/brseModes";
import { useRoomExpiry } from "../features/room/useRoomExpiry";
import { BrseToggleControl } from "./BrseToggleControl";
import { ConnectionBadge } from "./ConnectionBadge";
import { CustomSelect, type CustomSelectOption } from "./CustomSelect";
import { RelayModeControl } from "./RelayModeControl";

const LOW_TIME_MS = 5 * 60 * 1000;

interface RoomTopBarProps {
  roomId: string;
  meetingLanguages: MeetingLanguage[];
  currentLanguage: Language;
  participantCount: number;
  expiresAt: string | null | undefined;
  connectionState: GatewayConnectionState;
  brseEnabled: boolean;
  brseRoomMode: BrseRoomMode;
  isTogglingBrse: boolean;
  canToggleBrse: boolean;
  /** False for participants: AI relay is shown read-only. */
  canManageAi?: boolean;
  /** Optional meeting title (falls back to the language bridge). */
  title?: string | null;
  locked?: boolean;
  onChangeLanguage: (language: Language) => void;
  onToggleBrse: (nextEnabled: boolean) => void;
  relayMode: BrseOutputMode;
  relayModes: BrseOutputMode[];
  isUpdatingRelayMode: boolean;
  canChangeRelayMode: boolean;
  onChangeRelayMode: (mode: BrseOutputMode) => void;
  /** Permanent recording indicator (REC + elapsed time). */
  recordingIndicator?: ReactNode;
}

export function RoomTopBar({
  roomId,
  meetingLanguages,
  currentLanguage,
  participantCount,
  expiresAt,
  connectionState,
  brseEnabled,
  brseRoomMode,
  isTogglingBrse,
  canToggleBrse,
  canManageAi = true,
  title,
  locked = false,
  onChangeLanguage,
  onToggleBrse,
  relayMode,
  relayModes,
  isUpdatingRelayMode,
  canChangeRelayMode,
  onChangeRelayMode,
  recordingIndicator,
}: RoomTopBarProps) {
  const languageOptions =
    meetingLanguages.length > 0 ? meetingLanguages : [currentLanguage];
  const selectOptions: Array<CustomSelectOption<Language>> = languageOptions.map((item) => ({
    value: item,
    label: getLanguageLabel(item),
  }));

  const { remainingLabel, remainingMs, isExpired } = useRoomExpiry(expiresAt);
  const timeIsLow = !isExpired && remainingMs < LOW_TIME_MS;

  return (
    <header className="room-header">
      <div className="room-header-identity">
        <span className="brand-mark" aria-hidden="true">MQ</span>
        <div className="room-header-text">
          <h1 className="room-title">{title?.trim() || formatMeetingLanguageBridge(meetingLanguages)}</h1>
          <p className="room-meta">
            {title?.trim() ? <span className="room-meta-item">{formatMeetingLanguageBridge(meetingLanguages)}</span> : null}
            <span className="mono" title="Room ID">{roomId}</span>
            {locked ? (
              <span className="room-meta-item" title="Locked by the host: nobody new can join.">
                <Lock size={13} aria-hidden="true" />
                Locked
              </span>
            ) : null}
            <span className="room-meta-item">
              <Users size={13} aria-hidden="true" />
              {participantCount}
              <span className="sr-only"> participants</span>
            </span>
            {remainingLabel ? (
              <span
                className={[
                  "room-meta-item",
                  isExpired ? "is-danger" : timeIsLow ? "is-warning" : "",
                ].filter(Boolean).join(" ")}
              >
                <Clock size={13} aria-hidden="true" />
                {isExpired ? "Ended" : `${remainingLabel} left`}
              </span>
            ) : null}
          </p>
        </div>
      </div>

      <div className="room-header-controls">
        {recordingIndicator}
        <ConnectionBadge state={connectionState} />
        <div className="room-header-language">
          <CustomSelect
            value={currentLanguage}
            options={selectOptions}
            disabled={meetingLanguages.length === 0}
            onChange={onChangeLanguage}
            ariaLabel="Your language"
            size="compact"
          />
        </div>
        <BrseToggleControl
          enabled={brseEnabled}
          mode={brseRoomMode}
          languageCount={meetingLanguages.length}
          pending={isTogglingBrse}
          disabled={!canToggleBrse}
          readOnly={!canManageAi}
          onToggle={onToggleBrse}
        />
        {/* Desktop only; on smaller screens the same control lives in Settings → AI relay. */}
        <div className="room-header-relay-mode" title={canManageAi ? undefined : "Only the host or a co-host can change the AI relay mode."}>
          <RelayModeControl
            mode={relayMode}
            modes={relayModes}
            pending={isUpdatingRelayMode}
            disabled={!canChangeRelayMode}
            onChange={onChangeRelayMode}
          />
        </div>
      </div>
    </header>
  );
}
