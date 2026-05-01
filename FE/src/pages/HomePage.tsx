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
    <main className="home-page">
      <section className="hero-card">
        <div className="hero-copy">
          <span className="eyebrow">brseAI Meeting Platform</span>
          <h1>Realtime multilingual meetings without a separate interpreter.</h1>
          <p>
            Create a room, lock the room pair up front, invite participants by
            link, and let each person hear translated audio routed to their own
            language.
          </p>

          <div className="hero-pills">
            <span>Video + audio</span>
            <span>7 meeting languages</span>
            <span>Transcript streaming</span>
          </div>
        </div>

        <div className="hero-actions panel">
          <h2>Start a room</h2>
          <p>Create an instant room, choose the meeting pair here, or jump into an existing one.</p>

          <div className="field-section">
            <div className="field-section-header">
              <strong>Meeting languages</strong>
              <p>Choose exactly two different languages for this room before anyone joins.</p>
            </div>

            <div className="field-row-two">
              <label className="field">
                <span>Meeting language A</span>
                <select
                  value={firstMeetingLanguage}
                  onChange={(event) =>
                    handleFirstMeetingLanguageChange(event.target.value as MeetingLanguage | "")
                  }
                >
                  <option value="">Select a language</option>
                  {SUPPORTED_MEETING_LANGUAGES.map((language) => (
                    <option key={`first-${language}`} value={language}>
                      {getLanguageLabel(language)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span>Meeting language B</span>
                <select
                  value={secondMeetingLanguage}
                  onChange={(event) =>
                    handleSecondMeetingLanguageChange(event.target.value as MeetingLanguage | "")
                  }
                >
                  <option value="">Select a language</option>
                  {SUPPORTED_MEETING_LANGUAGES.map((language) => (
                    <option key={`second-${language}`} value={language}>
                      {getLanguageLabel(language)}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <p className="field-hint">
              Meeting bridge: {selectedMeetingLanguages.length === 2
                ? formatMeetingLanguageBridge(selectedMeetingLanguages)
                : "Select two languages"}
            </p>

            {createValidationError ? <div className="inline-error">{createValidationError}</div> : null}
            {createError ? <div className="inline-error">{createError}</div> : null}
          </div>

          <button
            className="button-primary"
            type="button"
            onClick={() => {
              void handleCreateRoom();
            }}
            disabled={creating}
          >
            {creating ? "Creating..." : "Create Room"}
          </button>

          <div className="divider">
            <span>or</span>
          </div>

          <label className="field">
            <span>Join existing room</span>
            <input
              value={roomInput}
              onChange={(event) => {
                setRoomInput(event.target.value);
                setJoinLookupError(null);
              }}
              placeholder="rm_... or room link"
            />
          </label>

          <button className="button-secondary" type="button" onClick={handleJoinExisting}>
            Open Room
          </button>

          {joinLookupError ? <div className="inline-error">{joinLookupError}</div> : null}

          <div className="divider">
            <span>dev</span>
          </div>

          <Link
            to="/test"
            className="button-secondary"
            style={{
              textAlign: "center",
              textDecoration: "none",
              display: "block",
              padding: "14px 18px",
              borderRadius: 16,
              fontWeight: 700,
            }}
          >
            Mic &amp; Translation Test
          </Link>
        </div>
      </section>
    </main>
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
