import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import {
  getLanguageLabel,
  isMeetingLanguage,
  SUPPORTED_MEETING_LANGUAGES,
} from "../lib/languages";
import { extractRoomId } from "../lib/rooms";
import type { MeetingLanguage } from "../types/api";

export function HomePage() {
  const navigate = useNavigate();
  const [roomInput, setRoomInput] = useState("");
  const [firstMeetingLanguage, setFirstMeetingLanguage] = useState<MeetingLanguage | "">("");
  const [secondMeetingLanguage, setSecondMeetingLanguage] = useState<MeetingLanguage | "">("");
  const [creating, setCreating] = useState(false);
  const [createValidationError, setCreateValidationError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [joinLookupError, setJoinLookupError] = useState<string | null>(null);

  function handleFirstMeetingLanguageChange(nextLanguage: MeetingLanguage | "") {
    setFirstMeetingLanguage(nextLanguage);
    setCreateError(null);
    setCreateValidationError(
      nextLanguage && nextLanguage === secondMeetingLanguage
        ? "Meeting languages must be two different languages."
        : null,
    );
  }

  function handleSecondMeetingLanguageChange(nextLanguage: MeetingLanguage | "") {
    setSecondMeetingLanguage(nextLanguage);
    setCreateError(null);
    setCreateValidationError(
      nextLanguage && nextLanguage === firstMeetingLanguage
        ? "Meeting languages must be two different languages."
        : null,
    );
  }

  async function handleCreateRoom() {
    if (!firstMeetingLanguage || !secondMeetingLanguage) {
      setCreateValidationError("Please select both meeting languages.");
      return;
    }

    if (firstMeetingLanguage === secondMeetingLanguage) {
      setCreateValidationError("Meeting languages must be two different languages.");
      return;
    }

    if (!isMeetingLanguage(firstMeetingLanguage) || !isMeetingLanguage(secondMeetingLanguage)) {
      setCreateValidationError("Meeting language selection is invalid.");
      return;
    }

    setCreating(true);
    setCreateError(null);
    setCreateValidationError(null);

    try {
      const response = await api.createRoom({
        meeting_languages: [firstMeetingLanguage, secondMeetingLanguage],
      });
      navigate(`/rooms/${response.room.room_id}`);
    } catch (error) {
      setCreateError(
        error instanceof ApiError
          ? mapCreateRoomError(error)
          : "Could not create room. Check backend connectivity.",
      );
    } finally {
      setCreating(false);
    }
  }

  function handleJoinExisting() {
    const roomId = extractRoomId(roomInput);
    if (!roomId) {
      setJoinLookupError("Enter a valid room id or a /rooms/{room_id} link.");
      return;
    }

    setJoinLookupError(null);
    navigate(`/rooms/${roomId}`);
  }

  return (
    <main className="home-page product-home">
      <section className="landing-shell landing-shell-minimal">
        <header className="landing-header">
          <div className="landing-brand">
            <span className="landing-brand-mark">MQ</span>
            <strong>MeetQ</strong>
          </div>
          <Link to="/test" className="utility-link">
            Mic test
          </Link>
        </header>

        <div className="create-room-layout">
          <CreateRoomPanel
            firstMeetingLanguage={firstMeetingLanguage}
            secondMeetingLanguage={secondMeetingLanguage}
            creating={creating}
            createValidationError={createValidationError}
            createError={createError}
            onFirstLanguageChange={handleFirstMeetingLanguageChange}
            onSecondLanguageChange={handleSecondMeetingLanguageChange}
            onCreateRoom={() => {
              void handleCreateRoom();
            }}
          />

          <JoinExistingRoomPanel
            roomInput={roomInput}
            joinLookupError={joinLookupError}
            onRoomInputChange={(value) => {
              setRoomInput(value);
              setJoinLookupError(null);
            }}
            onOpenRoom={handleJoinExisting}
          />
        </div>
      </section>
    </main>
  );
}

function CreateRoomPanel({
  firstMeetingLanguage,
  secondMeetingLanguage,
  creating,
  createValidationError,
  createError,
  onFirstLanguageChange,
  onSecondLanguageChange,
  onCreateRoom,
}: {
  firstMeetingLanguage: MeetingLanguage | "";
  secondMeetingLanguage: MeetingLanguage | "";
  creating: boolean;
  createValidationError: string | null;
  createError: string | null;
  onFirstLanguageChange: (language: MeetingLanguage | "") => void;
  onSecondLanguageChange: (language: MeetingLanguage | "") => void;
  onCreateRoom: () => void;
}) {
  return (
    <section className="create-room-panel">
      <div className="create-room-topline">
        <div>
          <span className="product-kicker">Create</span>
          <h1>Create room</h1>
        </div>
        <div className="create-room-badges" aria-label="Room defaults">
          <span>30 min</span>
          <span>BRSE relay</span>
        </div>
      </div>

      <div className="language-pair-picker">
        <LanguageSelectCard
          label="Language A"
          value={firstMeetingLanguage}
          onChange={onFirstLanguageChange}
        />
        <div className="language-bridge-glyph" aria-hidden="true">to</div>
        <LanguageSelectCard
          label="Language B"
          value={secondMeetingLanguage}
          onChange={onSecondLanguageChange}
        />
      </div>

      {createValidationError ? <div className="inline-error">{createValidationError}</div> : null}
      {createError ? <div className="inline-error">{createError}</div> : null}

      <button
        className="create-room-cta"
        type="button"
        onClick={onCreateRoom}
        disabled={creating}
      >
        {creating ? "Creating..." : "Create Room"}
      </button>
    </section>
  );
}

function JoinExistingRoomPanel({
  roomInput,
  joinLookupError,
  onRoomInputChange,
  onOpenRoom,
}: {
  roomInput: string;
  joinLookupError: string | null;
  onRoomInputChange: (value: string) => void;
  onOpenRoom: () => void;
}) {
  return (
    <section className="join-existing-panel">
      <span>Open room</span>
      <div className="join-existing-row">
        <input
          value={roomInput}
          onChange={(event) => onRoomInputChange(event.target.value)}
          placeholder="rm_... or room link"
        />
        <button type="button" onClick={onOpenRoom}>
          Open
        </button>
      </div>

      {joinLookupError ? <div className="inline-error">{joinLookupError}</div> : null}
    </section>
  );
}

function LanguageSelectCard({
  label,
  value,
  onChange,
}: {
  label: string;
  value: MeetingLanguage | "";
  onChange: (language: MeetingLanguage | "") => void;
}) {
  return (
    <label className={value ? "language-select-card has-value" : "language-select-card"}>
      <span>{label}</span>
      <strong>{value ? getLanguageLabel(value) : "Choose language"}</strong>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as MeetingLanguage | "")}
      >
        <option value="">Select a language</option>
        {SUPPORTED_MEETING_LANGUAGES.map((language) => (
          <option key={`${label}-${language}`} value={language}>
            {getLanguageLabel(language)}
          </option>
        ))}
      </select>
    </label>
  );
}

function mapCreateRoomError(error: ApiError): string {
  if (error.code === "invalid_meeting_languages") {
    if (error.details?.expected === 2) {
      return "Choose exactly two meeting languages for the room.";
    }

    if (error.details?.unique) {
      return "Meeting languages must be two different languages.";
    }

    const unsupportedLanguages = error.details?.unsupported;
    if (Array.isArray(unsupportedLanguages)) {
      const unsupportedLabels = unsupportedLanguages
        .filter((language): language is string => typeof language === "string")
        .map((language) => (isMeetingLanguage(language) ? getLanguageLabel(language) : language));
      return unsupportedLabels.length > 0
        ? `Unsupported meeting language selection: ${unsupportedLabels.join(", ")}.`
        : "Meeting languages must be selected from the supported room language list.";
    }

    return "Meeting languages are invalid for room creation.";
  }

  return error.message;
}
