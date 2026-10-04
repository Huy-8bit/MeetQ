import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Clock, Lock } from "lucide-react";
import {
  formatRoomLanguageList,
  getLanguageLabel,
} from "../lib/languages";
import {
  getBrseModeDescription,
  isBrseAudioExpected,
  resolveBrseRoomMode,
  type BrseRoomMode,
} from "../lib/brseModes";
import { formatExpiresAtHuman, useRoomExpiry } from "../features/room/useRoomExpiry";
import { useAuthUser } from "../auth/AuthProvider";
import { UserMenu } from "../auth/UserMenu";
import { loadUserPrefs, saveUserPrefs } from "../lib/userPrefs";
import { isRecordingActive } from "../types/recording";
import type { MeetingLanguage, ParticipantSnapshot, RoomSnapshotResponse } from "../types/api";
import { CustomSelect, type CustomSelectOption } from "./CustomSelect";
import { Alert } from "./ui/Alert";
import { Badge } from "./ui/Badge";
import { Button, buttonClassName } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { Field } from "./ui/Field";
import { PasswordInput } from "./ui/PasswordInput";

interface JoinRoomCardProps {
  room: RoomSnapshotResponse["room"];
  participants: RoomSnapshotResponse["participants"];
  meetingLanguages: MeetingLanguage[];
  isExpired: boolean;
  onJoin: (payload: { displayName: string; language: MeetingLanguage; password?: string }) => Promise<void>;
  isSubmitting: boolean;
  error: string | null;
  /** Shown under the password field (e.g. "Incorrect meeting password."). */
  passwordError?: string | null;
  onPasswordEdited?: () => void;
}

export function JoinRoomCard({
  room,
  participants,
  meetingLanguages,
  isExpired,
  onJoin,
  isSubmitting,
  error,
  passwordError = null,
  onPasswordEdited,
}: JoinRoomCardProps) {
  const user = useAuthUser();
  const prefs = loadUserPrefs(user?.id);
  const savedLang = meetingLanguages.includes(prefs.language as MeetingLanguage)
    ? (prefs.language as MeetingLanguage)
    : "";
  // A name this user typed before wins; otherwise start from their Google name.
  const [displayName, setDisplayName] = useState(prefs.displayName || user?.name || "");
  const [language, setLanguage] = useState<MeetingLanguage | "">(savedLang);
  const [validationError, setValidationError] = useState<string | null>(null);
  // Kept in memory only for this form; cleared after a successful join (unmount).
  const [password, setPassword] = useState("");
  const [passwordMissing, setPasswordMissing] = useState(false);
  const passwordRequired = Boolean(room.password_required);

  useEffect(() => {
    if (meetingLanguages.length === 0) {
      setLanguage("");
      return;
    }

    if (language && !meetingLanguages.includes(language)) {
      setLanguage(meetingLanguages[0]);
      return;
    }

    if (!language) {
      // Room languages can arrive after mount; restore the remembered choice then.
      const remembered = meetingLanguages.find((item) => item === prefs.language);
      if (remembered) {
        setLanguage(remembered);
      } else if (meetingLanguages.length === 1) {
        setLanguage(meetingLanguages[0]);
      }
    }
  }, [language, meetingLanguages, prefs.language]);

  const roomLanguagesUnavailable = meetingLanguages.length === 0;
  const humanParticipants = participants.filter(
    (participant) => isHumanParticipant(participant),
  );
  const virtualParticipants = participants.filter(
    (participant) => !isHumanParticipant(participant),
  );
  const brseRoomMode = resolveBrseRoomMode(room);
  const brseAudioExpected = isBrseAudioExpected(room);
  const languageOptions: Array<CustomSelectOption<MeetingLanguage | "">> =
    roomLanguagesUnavailable
      ? [
          {
            value: language,
            label: "Room languages unavailable",
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

    if (roomLanguagesUnavailable) {
      setValidationError(
        "Room languages are unavailable. Reload room snapshot or ask the host to recreate the room.",
      );
      return;
    }

    if (!language) {
      setValidationError("Choose your language from the room languages.");
      return;
    }

    if (!meetingLanguages.includes(language)) {
      setValidationError(
        `Choose one of the room languages: ${formatRoomLanguageList(meetingLanguages)}.`,
      );
      return;
    }

    if (passwordRequired && !password) {
      setPasswordMissing(true);
      return;
    }

    setValidationError(null);
    saveUserPrefs(displayName.trim(), language, user?.id, user?.name);
    await onJoin({
      displayName: displayName.trim(),
      language,
      ...(passwordRequired ? { password } : {}),
    });
  }

  const isCaptionOnly = brseRoomMode === "text_only" && meetingLanguages.length === 1;
  const relayLabel = brseRoomMode === "off"
    ? "Off"
    : isCaptionOnly
      ? "Captions"
      : getBrseModeDescription(brseRoomMode);

  return (
    <div className="lobby">
      <header className="lobby-nav">
        <Link to="/" className="brand" aria-label="MeetQ home">
          <span className="brand-mark" aria-hidden="true">MQ</span>
          MeetQ
        </Link>
        <UserMenu />
      </header>

      <main className="lobby-main">
        <section className="card lobby-card" aria-labelledby="lobby-title">
          <div className="lobby-summary">
            <h1 id="lobby-title" className="lobby-title">
              {isExpired ? "Meeting ended" : "Join meeting"}
            </h1>
            <dl className="meta-list">
              <div className="meta-item">
                <dt>Room</dt>
                <dd className="mono">{room.room_id}</dd>
              </div>
              <div className="meta-item">
                <dt>Languages</dt>
                <dd>{formatLanguageBridge(meetingLanguages)}</dd>
              </div>
              <div className="meta-item">
                <dt>AI relay</dt>
                <dd>{relayLabel}</dd>
              </div>
              {passwordRequired ? (
                <div className="meta-item">
                  <dt>Access</dt>
                  <dd className="lobby-access">
                    <Lock size={14} aria-hidden="true" /> Password protected
                  </dd>
                </div>
              ) : null}
              {expirySummary ? (
                <div className="meta-item">
                  <dt>Time left</dt>
                  <dd className={isExpired ? "text-danger" : undefined}>{expirySummary}</dd>
                </div>
              ) : null}
            </dl>
          </div>

          {isExpired ? (
            <EmptyState
              icon={<Clock size={20} />}
              title="This meeting has ended"
              description="The room reached its time limit and no longer accepts participants."
              action={<Link to="/" className={buttonClassName({ variant: "secondary" })}>Back to home</Link>}
            />
          ) : (
            <div className="lobby-body">
              <form className="lobby-form" onSubmit={(event) => void handleSubmit(event)} noValidate>
                {isRecordingActive(room.recording) ? (
                  <Alert tone="warning">
                    <strong>This meeting is being recorded.</strong> By joining, your audio, video and screen share are
                    included in the recording.
                  </Alert>
                ) : null}
                <Field label="Your name" htmlFor="lobby-name">
                  <input
                    id="lobby-name"
                    className="input"
                    value={displayName}
                    onChange={(event) => {
                      setDisplayName(event.target.value);
                      setValidationError(null);
                    }}
                    maxLength={40}
                    autoComplete="name"
                    required
                  />
                </Field>

                <Field
                  label="Your language"
                  htmlFor="lobby-language"
                  helper="You'll hear and read others in this language."
                >
                  <CustomSelect
                    id="lobby-language"
                    value={language}
                    options={languageOptions}
                    onChange={(nextLanguage) => {
                      setLanguage(nextLanguage);
                      setValidationError(null);
                    }}
                    disabled={roomLanguagesUnavailable}
                    placeholder={
                      roomLanguagesUnavailable
                        ? "Room languages unavailable"
                        : "Select language"
                    }
                    ariaLabel="Your language"
                  />
                </Field>

                {passwordRequired ? (
                  <p className="lobby-password-note">
                    <Lock size={14} aria-hidden="true" /> This meeting requires a password.
                  </p>
                ) : null}
                {passwordRequired ? (
                  <Field
                    label="Meeting password"
                    htmlFor="lobby-password"
                    error={passwordError ?? (passwordMissing ? "Enter the meeting password." : null)}
                  >
                    <PasswordInput
                      id="lobby-password"
                      name="meeting-password"
                      value={password}
                      onChange={(event) => {
                        setPassword(event.target.value);
                        setPasswordMissing(false);
                        onPasswordEdited?.();
                      }}
                      maxLength={128}
                      autoComplete="off"
                      aria-invalid={passwordError || passwordMissing ? true : undefined}
                    />
                  </Field>
                ) : null}

                {roomLanguagesUnavailable ? (
                  <Alert tone="danger">
                    Room languages are unavailable. Reload the page or ask the host to recreate the room.
                  </Alert>
                ) : null}
                {validationError ? <Alert tone="danger">{validationError}</Alert> : null}
                {error ? <Alert tone="danger">{error}</Alert> : null}

                <Button
                  type="submit"
                  variant="primary"
                  size="lg"
                  block
                  loading={isSubmitting}
                  disabled={roomLanguagesUnavailable || !displayName.trim() || !language || (passwordRequired && !password)}
                >
                  {isSubmitting ? "Joining…" : "Join meeting"}
                </Button>
              </form>

              <ParticipantPreviewList
                hiddenParticipantCount={passwordRequired ? room.participant_count ?? 0 : null}
                humanParticipants={humanParticipants}
                virtualParticipants={virtualParticipants}
                brseRoomMode={brseRoomMode}
                brseAudioExpected={brseAudioExpected}
              />
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function ParticipantPreviewList({
  hiddenParticipantCount,
  humanParticipants,
  virtualParticipants,
  brseRoomMode,
  brseAudioExpected,
}: {
  /** Protected rooms show only a count until you join; null when names are visible. */
  hiddenParticipantCount: number | null;
  humanParticipants: ParticipantSnapshot[];
  virtualParticipants: ParticipantSnapshot[];
  brseRoomMode: BrseRoomMode;
  brseAudioExpected: boolean;
}) {
  const visibleHumans = humanParticipants.slice(0, 5);
  const hiddenHumanCount = Math.max(0, humanParticipants.length - visibleHumans.length);
  const brseParticipant = virtualParticipants.find(
    (participant) => participant.kind === "virtual_brse" || participant.is_virtual,
  );

  return (
    <section className="lobby-people" aria-labelledby="lobby-people-title">
      <h2 className="section-title" id="lobby-people-title">
        In this room <span className="text-tertiary">{hiddenParticipantCount ?? humanParticipants.length}</span>
      </h2>

      {hiddenParticipantCount !== null && hiddenParticipantCount > 0 ? (
        <p className="section-description">You'll see who's here after you join.</p>
      ) : (hiddenParticipantCount ?? humanParticipants.length) === 0 ? (
        <p className="section-description">No one has joined yet. You'll be the first.</p>
      ) : null}

      <ul className="people-list people-list--compact">
        {visibleHumans.map((participant) => (
          <li className="people-row" key={participant.participant_id}>
            <span className="avatar" aria-hidden="true">{getInitials(participant.display_name)}</span>
            <div className="people-main">
              <p className="people-name">
                {participant.display_name}
                {participant.is_host ? <Badge>Host</Badge> : null}
              </p>
              <p className="people-details">
                {getLanguageLabel(participant.language)} · {formatParticipantStatus(participant.status)}
              </p>
            </div>
          </li>
        ))}

        {hiddenHumanCount > 0 ? (
          <li className="people-more">
            +{hiddenHumanCount} more participant{hiddenHumanCount === 1 ? "" : "s"}
          </li>
        ) : null}

        {brseParticipant ? (
          <li className="people-row">
            <span className="avatar avatar--ai" aria-hidden="true">AI</span>
            <div className="people-main">
              <p className="people-name">{brseParticipant.display_name || "AI Relay"}</p>
              <p className="people-details">{getVirtualParticipantCopy(brseRoomMode, brseAudioExpected)}</p>
            </div>
          </li>
        ) : null}
      </ul>
    </section>
  );
}

function getInitials(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase()).join("") || "?";
}

function isHumanParticipant(participant: ParticipantSnapshot): boolean {
  return participant.kind !== "virtual_brse" && !participant.is_virtual;
}

function formatLanguageBridge(meetingLanguages: MeetingLanguage[]): string {
  return formatRoomLanguageList(meetingLanguages);
}

function formatParticipantStatus(status: ParticipantSnapshot["status"]): string {
  return status
    .split("_")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

function getVirtualParticipantCopy(
  mode: BrseRoomMode,
  brseAudioExpected: boolean,
): string {
  if (mode === "off") {
    return "BRSE relay is off";
  }

  if (mode === "text_only" || !brseAudioExpected) {
    return "Text relay virtual participant";
  }

  if (mode === "silent_summary") {
    return "Summary capture virtual participant";
  }

  return "Voice + text relay participant";
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
    return `${remainingLabel} left`;
  }

  return expiresLabel;
}
