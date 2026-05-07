import { useEffect, useState, type FormEvent } from "react";
import {
  formatMeetingLanguageBridge,
  getLanguageLabel,
} from "../lib/languages";
import { formatExpiresAtHuman, useRoomExpiry } from "../features/room/useRoomExpiry";
import { loadUserPrefs, saveUserPrefs } from "../lib/userPrefs";
import type { MeetingLanguage, ParticipantSnapshot, RoomSnapshotResponse } from "../types/api";
import { CustomSelect, type CustomSelectOption } from "./CustomSelect";

interface JoinRoomCardProps {
  room: RoomSnapshotResponse["room"];
  participants: RoomSnapshotResponse["participants"];
  meetingLanguages: MeetingLanguage[];
  isExpired: boolean;
  onJoin: (payload: { displayName: string; language: MeetingLanguage }) => Promise<void>;
  isSubmitting: boolean;
  error: string | null;
}

export function JoinRoomCard({
  room,
  participants,
  meetingLanguages,
  isExpired,
  onJoin,
  isSubmitting,
  error,
}: JoinRoomCardProps) {
  const prefs = loadUserPrefs();
  const savedLang = meetingLanguages.includes(prefs.language as MeetingLanguage)
    ? (prefs.language as MeetingLanguage)
    : "";
  const [displayName, setDisplayName] = useState(prefs.displayName);
  const [language, setLanguage] = useState<MeetingLanguage | "">(savedLang);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (language && meetingLanguages.length === 2 && !meetingLanguages.includes(language)) {
      setLanguage("");
    }
  }, [language, meetingLanguages]);

  const languagePairUnavailable = meetingLanguages.length !== 2;
  const humanParticipants = participants.filter(
    (participant) => isHumanParticipant(participant),
  );
  const virtualParticipants = participants.filter(
    (participant) => !isHumanParticipant(participant),
  );
  const brseEnabled = room.brse_enabled !== false;
  const languageOptions: Array<CustomSelectOption<MeetingLanguage | "">> =
    languagePairUnavailable
      ? [
          {
            value: language,
            label: "Meeting language pair unavailable",
            disabled: true,
          },
        ]
      : [
          { value: "", label: "Select language" },
          ...meetingLanguages.map((item) => ({
            value: item,
            label: getLanguageLabel(item),
          })),
        ];

  const expiresLabel = formatExpiresAtHuman(room.expires_at);
  const { remainingLabel } = useRoomExpiry(room.expires_at);
  const expirySummary = getExpirySummary({
    expiresLabel,
    isExpired,
    remainingLabel,
  });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (isExpired) {
      return;
    }

    if (!displayName.trim()) {
      setValidationError("Please enter your display name.");
      return;
    }

    if (languagePairUnavailable) {
      setValidationError(
        "Room meeting language pair is unavailable. Reload room snapshot or ask the host to recreate the room.",
      );
      return;
    }

    if (!language) {
      setValidationError("Choose your language from the room meeting pair.");
      return;
    }

    if (!meetingLanguages.includes(language)) {
      setValidationError(
        `Choose one of the room meeting languages: ${formatMeetingLanguageBridge(meetingLanguages)}.`,
      );
      return;
    }

    setValidationError(null);
    saveUserPrefs(displayName.trim(), language);
    await onJoin({
      displayName: displayName.trim(),
      language,
    });
  }

  return (
    <section className="join-room-shell">
      <div className="join-room-card join-room-card-minimal">
        <div className="join-room-topline">
          <div>
            <span className="product-kicker">Join</span>
            <h1>Enter room</h1>
          </div>

          <div className="join-room-id-badge" aria-label={`Room ${room.room_id}`}>
            <span>Room</span>
            <strong>{room.room_id}</strong>
          </div>
        </div>

        <div className="join-room-context-strip">
          <CompactMeta label="Languages" value={formatLanguageBridge(meetingLanguages)} />
          <RoomModeBadge brseEnabled={brseEnabled} />
          {expirySummary ? <CompactMeta label="Time" value={expirySummary} danger={isExpired} /> : null}
        </div>

        {isExpired ? (
          <div className="room-expired-state">
            <span className="room-expired-icon" aria-hidden="true">⏱</span>
            <strong>Meeting ended</strong>
            <p>Room expired.</p>
          </div>
        ) : (
          <>
            <div className="join-room-form-card">
              <div className="join-form-header">
                <h2>Join as</h2>
              </div>

              <form className="join-form redesigned-join-form" onSubmit={(event) => void handleSubmit(event)}>
                <label className="join-input-field">
                  <span>Your name</span>
                  <input
                    value={displayName}
                    onChange={(event) => {
                      setDisplayName(event.target.value);
                      setValidationError(null);
                    }}
                    maxLength={40}
                    placeholder="Display name"
                    required
                  />
                </label>

                <label className="join-input-field">
                  <span>Your language</span>
                  <CustomSelect
                    className="join-language-select"
                    value={language}
                    options={languageOptions}
                    onChange={(nextLanguage) => {
                      setLanguage(nextLanguage);
                      setValidationError(null);
                    }}
                    disabled={languagePairUnavailable}
                    placeholder={
                      languagePairUnavailable
                        ? "Meeting language pair unavailable"
                        : "Select language"
                    }
                    ariaLabel="Your language"
                  />
                </label>

                <button
                  className="join-room-cta"
                  type="submit"
                  disabled={isSubmitting || languagePairUnavailable}
                >
                  {isSubmitting ? "Joining..." : "Join Meeting"}
                </button>
              </form>

              {languagePairUnavailable ? (
                <div className="inline-error">
                  Room meeting language pair is unavailable. Reload room snapshot or ask the host to recreate the room.
                </div>
              ) : null}

              {validationError ? <div className="inline-error">{validationError}</div> : null}
              {error ? <div className="inline-error">{error}</div> : null}
            </div>

            <ParticipantPreviewList
              humanParticipants={humanParticipants}
              virtualParticipants={virtualParticipants}
            />
          </>
        )}
      </div>
    </section>
  );
}

function CompactMeta({
  label,
  value,
  danger = false,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <div className={danger ? "join-room-quick-stat is-expired" : "join-room-quick-stat"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function RoomModeBadge({ brseEnabled }: { brseEnabled: boolean }) {
  return (
    <div className={brseEnabled ? "join-mode-badge is-brse" : "join-mode-badge"}>
      <span>Mode</span>
      <strong>{brseEnabled ? "BRSE relay" : "Normal"}</strong>
    </div>
  );
}

function ParticipantPreviewList({
  humanParticipants,
  virtualParticipants,
}: {
  humanParticipants: ParticipantSnapshot[];
  virtualParticipants: ParticipantSnapshot[];
}) {
  const visibleHumans = humanParticipants.slice(0, 5);
  const hiddenHumanCount = Math.max(0, humanParticipants.length - visibleHumans.length);
  const brseParticipant = virtualParticipants.find(
    (participant) => participant.kind === "virtual_brse" || participant.is_virtual,
  );

  return (
    <section className="join-participant-preview">
      <div className="join-panel-header">
        <span>Already inside</span>
        <strong>{humanParticipants.length}</strong>
      </div>

      {humanParticipants.length === 0 ? (
        <div className="participant-empty-compact">
          <strong>No one yet</strong>
          {brseParticipant ? (
            <span className="virtual-participant-chip">AI relay virtual</span>
          ) : null}
        </div>
      ) : (
        <div className="participant-preview-list">
          {visibleHumans.map((participant) => (
            <div className="participant-preview" key={participant.participant_id}>
              <div>
                <strong>{participant.display_name}</strong>
                <p>{formatParticipantStatus(participant.status)}</p>
              </div>
              <div className="participant-row-tags">
                {participant.is_host ? <span className="badge badge-host">Host</span> : null}
                <span className="language-pill">
                  {getLanguageLabel(participant.language)}
                </span>
              </div>
            </div>
          ))}

          {hiddenHumanCount > 0 ? (
            <div className="participant-preview participant-preview-more">
              <strong>{hiddenHumanCount} more participant{hiddenHumanCount === 1 ? "" : "s"}</strong>
            </div>
          ) : null}

          {brseParticipant ? (
            <div className="participant-preview virtual-participant-preview">
              <div>
                <strong>{brseParticipant.display_name || "AI Relay"}</strong>
                <p>Virtual relay participant</p>
              </div>
              <span className="badge kind">AI relay</span>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

function isHumanParticipant(participant: ParticipantSnapshot): boolean {
  return participant.kind !== "virtual_brse" && !participant.is_virtual;
}

function formatLanguageBridge(meetingLanguages: MeetingLanguage[]): string {
  return meetingLanguages.length === 2
    ? formatMeetingLanguageBridge(meetingLanguages)
    : "Meeting languages unavailable";
}

function formatParticipantStatus(status: ParticipantSnapshot["status"]): string {
  return status
    .split("_")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

function getExpirySummary({
  expiresLabel,
  isExpired,
  remainingLabel,
}: {
  expiresLabel: string;
  isExpired: boolean;
  remainingLabel: string;
}): string {
  if (isExpired) {
    return "Expired";
  }

  if (remainingLabel) {
    return remainingLabel;
  }

  return expiresLabel;
}
