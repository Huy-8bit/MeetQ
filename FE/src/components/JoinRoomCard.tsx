import { useState } from "react";
import type { Language, RoomSnapshotResponse } from "../types/api";

interface JoinRoomCardProps {
  room: RoomSnapshotResponse["room"];
  participants: RoomSnapshotResponse["participants"];
  onJoin: (payload: { displayName: string; language: Language }) => Promise<void>;
  isSubmitting: boolean;
  error: string | null;
}

const SUPPORTED_LANGUAGES: Language[] = ["vi", "en", "ja"];

export function JoinRoomCard({
  room,
  participants,
  onJoin,
  isSubmitting,
  error,
}: JoinRoomCardProps) {
  const [displayName, setDisplayName] = useState("");
  const [language, setLanguage] = useState<Language>("vi");

  return (
    <section className="join-card panel">
      <div className="panel-header">
        <div>
          <h2>Join Room</h2>
          <p>Enter a display name, choose your language, and let BRSE AI relay across the room.</p>
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

      <form
        className="join-form"
        onSubmit={(event) => {
          event.preventDefault();
          void onJoin({
            displayName: displayName.trim(),
            language,
          });
        }}
      >
        <label className="field">
          <span>Name</span>
          <input
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            maxLength={40}
            placeholder="Your display name"
            required
          />
        </label>

        <label className="field">
          <span>Language</span>
          <select
            value={language}
            onChange={(event) => setLanguage(event.target.value as Language)}
          >
            {SUPPORTED_LANGUAGES.map((item) => (
              <option key={item} value={item}>
                {item.toUpperCase()}
              </option>
            ))}
          </select>
        </label>

        <button className="button-primary" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Joining..." : "Join Meeting"}
        </button>
      </form>

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
                    {participant.language.toUpperCase()}
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
