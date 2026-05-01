import { useEffect, useState, type FormEvent } from "react";
import {
  formatMeetingLanguagePair,
  getLanguageLabel,
} from "../lib/languages";
import { formatExpiresAtHuman } from "../features/room/useRoomExpiry";
import type { MeetingLanguage, RoomSnapshotResponse } from "../types/api";

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
  const [displayName, setDisplayName] = useState("");
  const [language, setLanguage] = useState<MeetingLanguage | "">("");
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (language && meetingLanguages.length === 2 && !meetingLanguages.includes(language)) {
      setLanguage("");
    }
  }, [language, meetingLanguages]);

  const languagePairUnavailable = meetingLanguages.length !== 2;
  const humanParticipants = participants.filter(
    (participant) => participant.kind !== "virtual_brse" && !participant.is_virtual,
  );
  const brseParticipantCount = participants.length - humanParticipants.length;

  const expiresLabel = formatExpiresAtHuman(room.expires_at);

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
        `Choose one of the room meeting languages: ${formatMeetingLanguagePair(meetingLanguages)}.`,
      );
      return;
    }

    setValidationError(null);
    await onJoin({
      displayName: displayName.trim(),
      language,
    });
  }

  return (
    <section className="join-room-shell">
      <div className="join-room-hero">
        <span className="product-kicker">Join meeting</span>
        <h1>{room.room_id}</h1>
        <p>{formatMeetingLanguagePair(meetingLanguages)}</p>

        <div className="join-room-meta-row">
          <div>
            <span>Participants</span>
            <strong>{room.participant_count}</strong>
          </div>
          <div>
            <span>Mode</span>
            <strong>{room.brse_enabled === false ? "Normal" : "BRSE relay"}</strong>
          </div>
          {expiresLabel ? (
            <div>
              <span>Expires at</span>
              <strong className={isExpired ? "expiry-label expiry-label-expired" : "expiry-label"}>
                {isExpired ? "Expired" : expiresLabel}
              </strong>
            </div>
          ) : null}
        </div>
      </div>

      {isExpired ? (
        <div className="join-room-card">
          <div className="room-expired-state">
            <span className="room-expired-icon" aria-hidden="true">⏱</span>
            <strong>This meeting has ended</strong>
            <p>The room expired and is no longer accepting new participants.</p>
          </div>
        </div>
      ) : (
        <div className="join-room-card">
          <div className="join-form-header">
            <span>Your setup</span>
            <h2>Enter the room</h2>
            <p>Name yourself and choose the language you will speak.</p>
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
              <select
                value={language}
                onChange={(event) => {
                  setLanguage(event.target.value as MeetingLanguage | "");
                  setValidationError(null);
                }}
                disabled={languagePairUnavailable}
              >
                {languagePairUnavailable ? (
                  <option value={language}>Meeting language pair unavailable</option>
                ) : (
                  <>
                    <option value="">Choose your language</option>
                    {meetingLanguages.map((item) => (
                      <option key={item} value={item}>
                        {getLanguageLabel(item)}
                      </option>
                    ))}
                  </>
                )}
              </select>
            </label>

            <div className="join-language-summary">
              <span>Meeting languages</span>
              <strong>{formatMeetingLanguagePair(meetingLanguages)}</strong>
            </div>

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

          <div className="join-participant-preview">
            <div className="join-participant-preview-header">
              <span>Already inside</span>
              <strong>{humanParticipants.length}</strong>
            </div>
            <div className="participant-preview-list">
              {humanParticipants.length === 0 ? (
                <p>No human participants connected yet.</p>
              ) : (
                humanParticipants.slice(0, 4).map((participant) => (
                  <div className="participant-preview" key={participant.participant_id}>
                    <div>
                      <strong>{participant.display_name}</strong>
                      <p>{participant.status}</p>
                    </div>
                    <div className="participant-row-tags">
                      <span className="language-pill">
                        {getLanguageLabel(participant.language)}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
            {brseParticipantCount > 0 ? (
              <p className="join-brse-note">BRSE AI relay will join automatically when relay mode is on.</p>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}
