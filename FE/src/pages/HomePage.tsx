import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
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
  const location = useLocation();
  const [roomInput, setRoomInput] = useState("");
  const [firstMeetingLanguage, setFirstMeetingLanguage] = useState<MeetingLanguage | "">("");
  const [secondMeetingLanguage, setSecondMeetingLanguage] = useState<MeetingLanguage | "">("");
  const [creating, setCreating] = useState(false);
  const [createValidationError, setCreateValidationError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [joinLookupError, setJoinLookupError] = useState<string | null>(null);
  const landingNotice = getLandingNotice(location.state);

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

        {landingNotice ? (
          <div className="banner banner-warning" role="status">
            {landingNotice}
          </div>
        ) : null}

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

      <footer className="landing-contact-wrap" aria-label="Contact">
        <div className="landing-contact">
          <a
            className="landing-contact-icon"
            href="mailto:johnnynguyen882@gmail.com"
            aria-label="Email contact"
            title="Email"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M3 6.75A1.75 1.75 0 0 1 4.75 5h14.5A1.75 1.75 0 0 1 21 6.75v10.5A1.75 1.75 0 0 1 19.25 19H4.75A1.75 1.75 0 0 1 3 17.25V6.75Zm2.09-.25 6.5 4.94a.75.75 0 0 0 .91 0l6.5-4.94H5.09Zm14.41 1.88-6.1 4.64a2.25 2.25 0 0 1-2.8 0L4.5 8.38v8.87c0 .14.11.25.25.25h14.5a.25.25 0 0 0 .25-.25V8.38Z" />
            </svg>
          </a>
          <a
            className="landing-contact-icon"
            href="https://www.linkedin.com/in/huy8bit/"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="LinkedIn profile"
            title="LinkedIn"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M6.84 8.2a1.56 1.56 0 1 1 0-3.12 1.56 1.56 0 0 1 0 3.12ZM5.5 9.5h2.68V19H5.5V9.5Zm4.22 0h2.57v1.3h.04c.36-.67 1.24-1.37 2.55-1.37 2.73 0 3.23 1.79 3.23 4.12V19h-2.68v-4.88c0-1.17-.02-2.67-1.63-2.67-1.63 0-1.88 1.27-1.88 2.58V19H9.72V9.5Z" />
            </svg>
          </a>
        </div>
      </footer>
    </main>
  );
}

function getLandingNotice(state: unknown): string | null {
  if (!state || typeof state !== "object") {
    return null;
  }

  const notice = (state as { notice?: unknown }).notice;
  return typeof notice === "string" ? notice : null;
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
