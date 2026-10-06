import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { AudioLines, Captions, FileText, History, Mic } from "lucide-react";
import { api, ApiError } from "../lib/api";
import {
  BRSE_CREATE_MODE_OPTIONS,
  buildCreateBrsePayload,
  getCreateModeDisabledReason,
  getEffectiveOutputMode,
  type BrseCreateMode,
} from "../lib/brseModes";
import {
  formatRoomLanguageList,
  getLanguageLabel,
  isMeetingLanguage,
  SUPPORTED_MEETING_LANGUAGES,
} from "../lib/languages";
import { extractRoomId } from "../lib/rooms";
import { hasRoomPasswordErrors, validateRoomPassword, type RoomPasswordErrors } from "../lib/roomAccess";
import type { MeetingLanguage, RoomAccess } from "../types/api";
import { Alert } from "../components/ui/Alert";
import { Button, buttonClassName } from "../components/ui/Button";
import { Field } from "../components/ui/Field";
import { SegmentedControl } from "../components/ui/SegmentedControl";
import { RoomAccessFields } from "../components/RoomAccessFields";
import { UserMenu } from "../auth/UserMenu";

const CREATE_BRSE_MODE_STORAGE_KEY = "meetq:create-brse-mode";

const FEATURES = [
  {
    icon: Captions,
    title: "Live captions in every language",
    text: "Each person speaks their own language and reads everyone else in theirs.",
  },
  {
    icon: AudioLines,
    title: "AI voice relay",
    text: "In two-language rooms, MeetQ can also speak the translation aloud.",
  },
  {
    icon: FileText,
    title: "Summary when you're done",
    text: "Key points, decisions and action items from the whole meeting.",
  },
];

export function HomePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [roomInput, setRoomInput] = useState("");
  const [selectedLanguages, setSelectedLanguages] = useState<MeetingLanguage[]>([]);
  const [brseCreateMode, setBrseCreateMode] = useState<BrseCreateMode>(
    () => loadCreateBrseModePreference(),
  );
  // Room password lives only in component state until the create request is sent.
  const [roomAccess, setRoomAccess] = useState<RoomAccess>("link");
  const [meetingTitle, setMeetingTitle] = useState("");
  const [roomPassword, setRoomPassword] = useState("");
  const [roomPasswordConfirm, setRoomPasswordConfirm] = useState("");
  const [passwordErrors, setPasswordErrors] = useState<RoomPasswordErrors>({});
  const [creating, setCreating] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [joinError, setJoinError] = useState<string | null>(null);
  const landingNotice = getLandingNotice(location.state);
  const roomDurationMinutes = useRoomDurationMinutes();

  useEffect(() => {
    saveCreateBrseModePreference(brseCreateMode);
  }, [brseCreateMode]);

  function toggleRoomLanguage(language: MeetingLanguage) {
    setSelectedLanguages((current) =>
      current.includes(language)
        ? current.filter((item) => item !== language)
        : [...current, language],
    );
    setCreateError(null);
    setValidationError(null);
  }

  async function handleCreateRoom() {
    if (selectedLanguages.length === 0) {
      setValidationError("Select at least one room language.");
      return;
    }
    if (!selectedLanguages.every((language) => isMeetingLanguage(language))) {
      setValidationError("Invalid language selection."); return;
    }
    if (roomAccess === "password") {
      const errors = validateRoomPassword(roomPassword, roomPasswordConfirm);
      setPasswordErrors(errors);
      if (hasRoomPasswordErrors(errors)) {
        return;
      }
    }

    setCreating(true);
    setCreateError(null);
    setValidationError(null);

    try {
      const res = await api.createRoom({
        room_languages: selectedLanguages,
        ...buildCreateBrsePayload(brseCreateMode, selectedLanguages),
        ...(roomAccess === "password" ? { access: "password" as const, password: roomPassword } : { access: "link" as const }),
        ...(meetingTitle.trim() ? { title: meetingTitle.trim() } : {}),
      });
      setMeetingTitle("");
      setRoomPassword("");
      setRoomPasswordConfirm("");
      navigate(`/rooms/${res.room.room_id}`);
    } catch (err) {
      setCreateError(
        err instanceof ApiError ? mapCreateRoomError(err) : "Could not create room.",
      );
    } finally {
      setCreating(false);
    }
  }

  function handleJoin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const roomId = extractRoomId(roomInput);
    if (!roomId) { setJoinError("Enter a valid room ID or link."); return; }
    setJoinError(null);
    navigate(`/rooms/${roomId}`);
  }

  const languageCount = selectedLanguages.length;
  const effectiveCreateMode = getEffectiveOutputMode(selectedLanguages, brseCreateMode);
  const canCreate = languageCount > 0;

  return (
    <div className="home">
      <header className="home-nav">
        <Link to="/" className="brand" aria-label="MeetQ home">
          <span className="brand-mark" aria-hidden="true">MQ</span>
          MeetQ
        </Link>
        <div className="nav-actions">
          <Link to="/meetings" className={buttonClassName({ variant: "ghost", size: "sm" })}>
            <History size={16} aria-hidden="true" />
            My meetings
          </Link>
          <Link to="/test" className={buttonClassName({ variant: "ghost", size: "sm" })}>
            <Mic size={16} aria-hidden="true" />
            Test your mic
          </Link>
          <UserMenu />
        </div>
      </header>

      <main className="home-main">
        <section className="home-intro" aria-labelledby="home-title">
          <h1 id="home-title" className="home-title">
            Meetings where everyone speaks their own language
          </h1>
          <p className="home-lead">
            MeetQ joins your call as an AI interpreter and relays what people say as live
            captions and voice.
          </p>

          <ul className="home-features">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="home-feature">
                <span className="home-feature-icon" aria-hidden="true">
                  <Icon size={18} />
                </span>
                <div>
                  <p className="home-feature-title">{title}</p>
                  <p className="home-feature-text">{text}</p>
                </div>
              </li>
            ))}
          </ul>

          <RelayPreview />
        </section>

        <div className="home-actions">
          {landingNotice ? <Alert tone="info">{landingNotice}</Alert> : null}

          <section className="card" aria-labelledby="create-room-title">
            <div className="card-body home-create">
              <div>
                <h2 id="create-room-title" className="card-title">Create a room</h2>
                <p className="card-description">Pick the languages people will speak.</p>
              </div>

              <Field
                label="Meeting title (optional)"
                htmlFor="meeting-title"
                helper="Helps you find it later in My meetings."
              >
                <input
                  id="meeting-title"
                  className="input"
                  value={meetingTitle}
                  onChange={(event) => setMeetingTitle(event.target.value)}
                  maxLength={120}
                  placeholder={
                    languageCount > 0 ? `${formatRoomLanguageList(selectedLanguages)} meeting` : "e.g. Weekly sync"
                  }
                  autoComplete="off"
                />
              </Field>

              <Field
                asGroup
                labelId="room-languages-label"
                label="Room languages"
                error={validationError}
                helper={
                  languageCount > 0
                    ? `${formatRoomLanguageList(selectedLanguages)} selected`
                    : "Select at least one language."
                }
              >
                <div className="chip-group" role="group" aria-labelledby="room-languages-label">
                  {SUPPORTED_MEETING_LANGUAGES.map((language) => (
                    <button
                      key={language}
                      type="button"
                      className="chip-toggle"
                      aria-pressed={selectedLanguages.includes(language)}
                      onClick={() => toggleRoomLanguage(language)}
                    >
                      {getLanguageLabel(language)}
                    </button>
                  ))}
                </div>
              </Field>

              <Field
                asGroup
                labelId="relay-mode-label"
                label="AI relay"
                helper={getCreateModeHelper(languageCount)}
              >
                <SegmentedControl
                  ariaLabelledBy="relay-mode-label"
                  value={effectiveCreateMode}
                  onChange={setBrseCreateMode}
                  options={BRSE_CREATE_MODE_OPTIONS.map((option) => {
                    const disabledReason = getCreateModeDisabledReason(languageCount, option.value);
                    return {
                      value: option.value,
                      label: option.label,
                      disabled: !!disabledReason,
                      title: disabledReason ?? option.detail,
                    };
                  })}
                />
              </Field>

              <RoomAccessFields
                access={roomAccess}
                password={roomPassword}
                confirm={roomPasswordConfirm}
                errors={passwordErrors}
                disabled={creating}
                onAccessChange={(access) => {
                  setRoomAccess(access);
                  setPasswordErrors({});
                  setCreateError(null);
                }}
                onPasswordChange={(value) => {
                  setRoomPassword(value);
                  setPasswordErrors({});
                }}
                onConfirmChange={(value) => {
                  setRoomPasswordConfirm(value);
                  setPasswordErrors((current) => ({ ...current, confirm: undefined }));
                }}
              />

              {createError ? <Alert tone="danger">{createError}</Alert> : null}

              <div className="home-create-footer">
                <Button
                  variant="primary"
                  size="lg"
                  block
                  loading={creating}
                  disabled={!canCreate}
                  onClick={() => { void handleCreateRoom(); }}
                >
                  {creating ? "Creating room…" : "Create room"}
                </Button>
                <p className="field-helper">
                  {roomDurationMinutes
                    ? `Rooms stay open for ${roomDurationMinutes} minutes. No account needed.`
                    : "Rooms close automatically after a set time. No account needed."}
                </p>
              </div>
            </div>
          </section>

          <section className="card" aria-labelledby="join-room-title">
            <form className="card-body home-join" onSubmit={handleJoin} noValidate>
              <h2 id="join-room-title" className="section-title">Have a room link?</h2>
              <Field label="Room ID or link" htmlFor="join-room-input" error={joinError}>
                <div className="home-join-row">
                  <input
                    id="join-room-input"
                    className="input"
                    value={roomInput}
                    onChange={(e) => { setRoomInput(e.target.value); setJoinError(null); }}
                    placeholder="rm_abc123 or https://…"
                    autoComplete="off"
                    aria-invalid={joinError ? true : undefined}
                  />
                  <Button type="submit" variant="secondary" size="lg">
                    Join
                  </Button>
                </div>
              </Field>
            </form>
          </section>
        </div>
      </main>

      <footer className="home-footer">
        <span>© MeetQ</span>
        <nav className="home-footer-links" aria-label="Contact">
          <a href="mailto:johnnynguyen882@gmail.com">Contact</a>
          <a href="https://www.linkedin.com/in/huy8bit/" target="_blank" rel="noopener noreferrer">
            LinkedIn
          </a>
        </nav>
      </footer>
    </div>
  );
}

/** Static example of what participants see in a room. */
function RelayPreview() {
  return (
    <figure className="relay-preview" aria-label="Example of a relayed sentence">
      <div className="relay-preview-row">
        <span className="relay-preview-lang">VI</span>
        <div>
          <p className="relay-preview-speaker">Linh · speaking</p>
          <p>Xin chào team, mình bắt đầu nhé.</p>
        </div>
      </div>
      <div className="relay-preview-row is-relay">
        <span className="relay-preview-lang">EN</span>
        <div>
          <p className="relay-preview-speaker">MeetQ relay</p>
          <p>Hello team, let&apos;s get started.</p>
        </div>
      </div>
      <div className="relay-preview-row is-relay">
        <span className="relay-preview-lang">JA</span>
        <div>
          <p className="relay-preview-speaker">MeetQ relay</p>
          <p>こんにちは、始めましょう。</p>
        </div>
      </div>
    </figure>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Room lifetime comes from the server config (ROOM_MEETING_DURATION_SECONDS), never hard-coded. */
function useRoomDurationMinutes(): number | null {
  const [minutes, setMinutes] = useState<number | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .getPublicConfig()
      .then((config) => {
        if (!cancelled && config.room_meeting_duration_seconds > 0) {
          setMinutes(Math.round(config.room_meeting_duration_seconds / 60));
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  return minutes;
}

function getLandingNotice(state: unknown): string | null {
  if (!state || typeof state !== "object") return null;
  const notice = (state as { notice?: unknown }).notice;
  return typeof notice === "string" ? notice : null;
}

function loadCreateBrseModePreference(): BrseCreateMode {
  if (typeof window === "undefined") {
    return "voice_text";
  }

  try {
    const stored = window.localStorage.getItem(CREATE_BRSE_MODE_STORAGE_KEY);
    return isBrseCreateMode(stored) ? stored : "voice_text";
  } catch {
    return "voice_text";
  }
}

function saveCreateBrseModePreference(mode: BrseCreateMode): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(CREATE_BRSE_MODE_STORAGE_KEY, mode);
  } catch {
    // Preference storage is optional.
  }
}

function isBrseCreateMode(value: unknown): value is BrseCreateMode {
  return value === "voice_text" || value === "text_only" || value === "off";
}

function getCreateModeHelper(languageCount: number): string {
  if (languageCount === 0) {
    return "Choose languages first to see which relay modes are available.";
  }

  if (languageCount === 1) {
    return "Single-language rooms get a live transcript and captions.";
  }

  if (languageCount === 2) {
    return "Voice + Text speaks the translation aloud and shows captions.";
  }

  return "Voice relay supports up to 2 languages, so this room uses text relay.";
}

function mapCreateRoomError(error: ApiError): string {
  if (error.code === "invalid_room_password_setting") {
    return error.message || "Check the room password.";
  }
  if (error.code === "invalid_room_languages" || error.code === "invalid_meeting_languages") {
    if (error.details?.min === 1 || error.details?.required) return "Select at least one room language.";
    if (error.details?.unique) return "Remove duplicate languages.";
    const unsupported = error.details?.unsupported;
    if (Array.isArray(unsupported)) {
      const labels = unsupported
        .filter((l): l is string => typeof l === "string")
        .map((l) => (isMeetingLanguage(l) ? getLanguageLabel(l) : l));
      return labels.length > 0 ? `Unsupported language: ${labels.join(", ")}.` : "Invalid language selection.";
    }
    return "Invalid room languages.";
  }
  return error.message;
}
