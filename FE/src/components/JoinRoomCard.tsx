import { useEffect, useState, type FormEvent } from "react";
import {
  formatMeetingLanguageBridge,
  getLanguageLabel,
} from "../lib/languages";
import {
  getBrseModeLabel,
  isBrseAudioExpected,
  resolveBrseRoomMode,
  type BrseRoomMode,
} from "../lib/brseModes";
import { formatExpiresAtHuman, useRoomExpiry } from "../features/room/useRoomExpiry";
import { loadUserPrefs, saveUserPrefs } from "../lib/userPrefs";
import { useRevealMotion } from "../lib/motion";
import { useTextAnimations } from "../lib/textAnimations";
import type { MeetingLanguage, ParticipantSnapshot, RoomSnapshotResponse } from "../types/api";
import { CustomSelect, type CustomSelectOption } from "./CustomSelect";
import { MotionButton } from "./MotionButton";

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
  const joinMotionRef = useRevealMotion<HTMLDivElement>({
    selector: "[data-join-motion]",
    distance: 14,
    duration: 460,
    stagger: 54,
    scaleFrom: 0.992,
  });
  useTextAnimations(joinMotionRef, {
    dependencies: [
      room.room_id,
      isExpired,
      participants.length,
      meetingLanguages.join("-"),
    ],
  });
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
  const brseRoomMode = resolveBrseRoomMode(room);
  const brseAudioExpected = isBrseAudioExpected(room);
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
  const joinAttentionKey =
    !isExpired && displayName.trim() && language ? `${displayName.trim()}-${language}` : null;

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
      <div className="join-room-card join-room-card-minimal join-room-card-premium" ref={joinMotionRef}>
        <span className="join-room-ambient-sweep join-room-ambient-sweep-a" aria-hidden="true" />
        <span className="join-room-ambient-sweep join-room-ambient-sweep-b" aria-hidden="true" />

        <div className="join-room-topline join-room-hero-line" data-join-motion>
          <div className="join-room-title-block">
            <span className="product-kicker" data-text-animate="fade">Room access</span>
            <h1 data-text-animate="line">Enter MeetQ room</h1>
            <p data-text-animate="fade">
              Confirm your name and language before joining the live AI relay.
            </p>
          </div>

          <div className="join-room-id-badge" aria-label={`Room ${room.room_id}`} data-text-animate="fade">
            <span>Room ID</span>
            <strong>{room.room_id}</strong>
          </div>
        </div>

        <div className="join-room-context-strip" data-join-motion>
          <CompactMeta label="Languages" value={formatLanguageBridge(meetingLanguages)} />
          <RoomModeBadge mode={brseRoomMode} />
          {expirySummary ? <CompactMeta label="Time" value={expirySummary} danger={isExpired} /> : null}
        </div>

        {isExpired ? (
          <div className="room-expired-state" data-join-motion>
            <span className="room-expired-icon" aria-hidden="true">⏱</span>
            <strong data-text-animate="fade">Meeting ended</strong>
            <p data-text-animate="fade">Room expired.</p>
          </div>
        ) : (
          <div className="join-room-body-grid">
            <div className="join-room-form-card" data-join-motion>
              <div className="join-form-header">
                <span data-text-animate="fade">Profile</span>
                <h2 data-text-animate="fade">Join as participant</h2>
              </div>

              <form className="join-form redesigned-join-form" onSubmit={(event) => void handleSubmit(event)}>
                <label className="join-input-field">
                  <span data-text-animate="fade">Your name</span>
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
                  <span data-text-animate="fade">Your language</span>
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

                <MotionButton
                  className="join-room-cta"
                  type="submit"
                  disabled={isSubmitting || languagePairUnavailable}
                  attentionKey={joinAttentionKey}
                  data-text-animate="cta"
                >
                  {isSubmitting ? "Joining..." : "Join Meeting"}
                </MotionButton>
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
              brseRoomMode={brseRoomMode}
              brseAudioExpected={brseAudioExpected}
            />
          </div>
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
    <div
      className={danger ? "join-room-quick-stat is-expired" : "join-room-quick-stat"}
      data-join-motion
    >
      <span data-text-animate="fade">{label}</span>
      <strong data-text-animate="fade">{value}</strong>
    </div>
  );
}

function RoomModeBadge({ mode }: { mode: BrseRoomMode }) {
  const isBrse = mode !== "off";
  const isTextOnly = mode === "text_only";

  return (
    <div
      className={[
        "join-mode-badge",
        isBrse ? "is-brse" : "",
        isTextOnly ? "is-text-only" : "",
      ].filter(Boolean).join(" ")}
      data-join-motion
    >
      <span data-text-animate="fade">Mode</span>
      <strong data-text-animate="fade">{getBrseModeLabel(mode)}</strong>
    </div>
  );
}

function ParticipantPreviewList({
  humanParticipants,
  virtualParticipants,
  brseRoomMode,
  brseAudioExpected,
}: {
  humanParticipants: ParticipantSnapshot[];
  virtualParticipants: ParticipantSnapshot[];
  brseRoomMode: BrseRoomMode;
  brseAudioExpected: boolean;
}) {
  const previewMotionRef = useRevealMotion<HTMLElement>({
    selector: "[data-preview-motion]",
    distance: 8,
    duration: 320,
    stagger: 36,
    scaleFrom: 0.996,
    dependencies: [humanParticipants.length, virtualParticipants.length, brseRoomMode, brseAudioExpected],
  });
  useTextAnimations(previewMotionRef, {
    dependencies: [humanParticipants.length, virtualParticipants.length, brseRoomMode, brseAudioExpected],
  });
  const visibleHumans = humanParticipants.slice(0, 5);
  const hiddenHumanCount = Math.max(0, humanParticipants.length - visibleHumans.length);
  const brseParticipant = virtualParticipants.find(
    (participant) => participant.kind === "virtual_brse" || participant.is_virtual,
  );

  return (
    <section className="join-participant-preview" ref={previewMotionRef} data-join-motion>
      <div className="join-panel-header" data-preview-motion>
        <span data-text-animate="fade">Already inside</span>
        <strong data-text-animate="fade">{humanParticipants.length}</strong>
      </div>

      {humanParticipants.length === 0 ? (
        <div className="participant-empty-compact" data-preview-motion>
          <strong data-text-animate="fade">No one yet</strong>
          {brseParticipant ? (
            <span className="virtual-participant-chip" data-text-animate="fade">
              {getVirtualParticipantBadge(brseRoomMode, brseAudioExpected)}
            </span>
          ) : null}
        </div>
      ) : (
        <div className="participant-preview-list">
          {visibleHumans.map((participant) => (
            <div
              className="participant-preview"
              key={participant.participant_id}
              data-preview-motion
            >
              <div>
                <strong data-text-animate="fade">{participant.display_name}</strong>
                <p data-text-animate="fade">{formatParticipantStatus(participant.status)}</p>
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
            <div className="participant-preview participant-preview-more" data-preview-motion>
              <strong data-text-animate="fade">{hiddenHumanCount} more participant{hiddenHumanCount === 1 ? "" : "s"}</strong>
            </div>
          ) : null}

          {brseParticipant ? (
            <div className="participant-preview virtual-participant-preview" data-preview-motion>
              <div>
                <strong data-text-animate="fade">{brseParticipant.display_name || "AI Relay"}</strong>
                <p data-text-animate="fade">{getVirtualParticipantCopy(brseRoomMode, brseAudioExpected)}</p>
              </div>
              <span className="badge kind" data-text-animate="fade">
                {getVirtualParticipantBadge(brseRoomMode, brseAudioExpected)}
              </span>
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

function getVirtualParticipantBadge(
  mode: BrseRoomMode,
  brseAudioExpected: boolean,
): string {
  if (mode === "off") {
    return "BRSE off";
  }

  if (mode === "text_only" || !brseAudioExpected) {
    return "BRSE text";
  }

  if (mode === "silent_summary") {
    return "BRSE summary";
  }

  return "AI relay";
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
