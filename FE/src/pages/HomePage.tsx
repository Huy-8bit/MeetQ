import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import {
  formatMeetingLanguageBridge,
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

  const selectedMeetingLanguages = [firstMeetingLanguage, secondMeetingLanguage].filter(
    (language): language is MeetingLanguage => isMeetingLanguage(language),
  );

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
      <section className="landing-shell">
        <header className="landing-header">
          <div className="landing-brand">
            <span className="landing-brand-mark">brseAI</span>
            <div>
              <strong>Multilingual meeting rooms</strong>
              <p>Video, relay, transcript, and chat in one live room.</p>
            </div>
          </div>
          <Link to="/test" className="utility-link">
            Mic &amp; Translation Test
          </Link>
        </header>

        <div className="landing-content">
          <section className="landing-intro">
            <span className="product-kicker">Meeting-first relay</span>
            <h1>Start a multilingual room without setting up an interpreter booth.</h1>
            <p>
              Choose the meeting language pair, share the room, and keep video,
              screen share, BRSE relay, transcript, and chat in one focused workspace.
            </p>
            <div className="landing-proof-row">
              <span>7 languages</span>
              <span>BRSE relay mode</span>
              <span>Live transcript</span>
            </div>
          </section>

          <section className="room-launch-panel">
            <div className="launch-section launch-section-primary">
              <div className="launch-section-header">
                <span>Create room</span>
                <h2>Set the meeting pair</h2>
                <p>Both participants choose from this pair when they join.</p>
              </div>

              <div className="language-pair-picker">
                <LanguageSelectCard
                  label="Language A"
                  value={firstMeetingLanguage}
                  onChange={handleFirstMeetingLanguageChange}
                />
                <div className="language-bridge-glyph" aria-hidden="true">to</div>
                <LanguageSelectCard
                  label="Language B"
                  value={secondMeetingLanguage}
                  onChange={handleSecondMeetingLanguageChange}
                />
              </div>

              <div className="meeting-bridge-preview">
                <span>Meeting bridge</span>
                <strong>
                  {selectedMeetingLanguages.length === 2
                    ? formatMeetingLanguageBridge(selectedMeetingLanguages)
                    : "Select two languages"}
                </strong>
              </div>

              {createValidationError ? <div className="inline-error">{createValidationError}</div> : null}
              {createError ? <div className="inline-error">{createError}</div> : null}

              <div className="create-room-policy-note">
                Meetings last 30 minutes
              </div>

              <button
                className="create-room-cta"
                type="button"
                onClick={() => {
                  void handleCreateRoom();
                }}
                disabled={creating}
              >
                {creating ? "Creating room..." : "Create Room"}
              </button>
            </div>

            <div className="launch-section launch-section-secondary">
              <div className="launch-section-header">
                <span>Join existing</span>
                <h2>Open a room</h2>
              </div>

              <div className="join-existing-row">
                <input
                  value={roomInput}
                  onChange={(event) => {
                    setRoomInput(event.target.value);
                    setJoinLookupError(null);
                  }}
                  placeholder="rm_... or room link"
                />
                <button type="button" onClick={handleJoinExisting}>
                  Open
                </button>
              </div>

              {joinLookupError ? <div className="inline-error">{joinLookupError}</div> : null}
            </div>
          </section>
        </div>
      </section>
    </main>
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
