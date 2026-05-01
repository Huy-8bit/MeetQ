import { useEffect, useState, type FormEvent } from "react";
import {
  formatMeetingLanguagePair,
  getLanguageLabel,
} from "../lib/languages";
import type { MeetingLanguage, RoomSnapshotResponse } from "../types/api";

interface JoinRoomCardProps {
  room: RoomSnapshotResponse["room"];
  participants: RoomSnapshotResponse["participants"];
  meetingLanguages: MeetingLanguage[];
  onJoin: (payload: { displayName: string; language: MeetingLanguage }) => Promise<void>;
  isSubmitting: boolean;
  error: string | null;
}

export function JoinRoomCard({
  room,
  participants,
  meetingLanguages,
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

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

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
    <section className="join-card panel">
      <div className="panel-header">
        <div>
          <h2>Join Room</h2>
          <p>Enter a display name and choose your language from the room meeting pair.</p>
        </div>
      </div>

      <div className="room-meta-grid">
        <div className="room-meta-item">
          <span>Room</span>
          <strong>{room.room_id}</strong>
        </div>
        <div className="room-meta-item">
          <span>Participants</span>
          <strong>
            {room.participant_count}/{room.participant_limit}
          </strong>
        </div>
        <div className="room-meta-item">
          <span>State</span>
          <strong>{room.state}</strong>
        </div>
      </div>

      <form className="join-form" onSubmit={(event) => void handleSubmit(event)}>
        <label className="field">
          <span>Name</span>
          <input
            value={displayName}
            onChange={(event) => {
              setDisplayName(event.target.value);
              setValidationError(null);
            }}
            maxLength={40}
            placeholder="Your display name"
            required
          />
        </label>

        <label className="field">
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

        <p className="field-hint">
          Meeting languages: {formatMeetingLanguagePair(meetingLanguages)}
        </p>

        <button
          className="button-primary"
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

      <div className="join-card-footer">
        <h4>Already inside</h4>
        <div className="participant-preview-list">
          {participants.length === 0 ? (
            <p>No one is connected yet.</p>
          ) : (
            participants.map((participant) => (
              <div className="participant-preview" key={participant.participant_id}>
                <div>
                  <strong>{participant.display_name}</strong>
                  <p>
                    {participant.kind === "virtual_brse" || participant.is_virtual
                      ? "AI relay participant"
                      : participant.status}
                  </p>
                </div>
                <div className="participant-row-tags">
                  {participant.kind === "virtual_brse" || participant.is_virtual ? (
                    <span className="badge kind">BRSE AI</span>
                  ) : null}
                  <span className="language-pill">
                    {getLanguageLabel(participant.language)}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
