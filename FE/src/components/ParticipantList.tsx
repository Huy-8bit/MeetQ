import { MicOff, MonitorUp } from "lucide-react";
import type { ParticipantSnapshot } from "../types/api";
import type { BrseRoomMode } from "../lib/brseModes";
import { getLanguageLabel } from "../lib/languages";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";

interface ParticipantListProps {
  participants: ParticipantSnapshot[];
  selfParticipantId?: string;
  isCurrentUserHost?: boolean;
  onMuteParticipant?: (participantId: string) => void;
  isMutingParticipant?: string | null;
  brseEnabled?: boolean;
  brseRoomMode?: BrseRoomMode;
  brseAudioExpected?: boolean;
  embedded?: boolean;
}

export function ParticipantList({
  participants,
  selfParticipantId,
  isCurrentUserHost = false,
  onMuteParticipant,
  isMutingParticipant,
  brseEnabled = true,
  brseRoomMode = "voice_text",
  brseAudioExpected = true,
}: ParticipantListProps) {
  const brsePeopleCopy = getBrsePeopleCopy({
    brseEnabled,
    brseRoomMode,
    brseAudioExpected,
  });

  if (participants.length === 0) {
    return (
      <EmptyState
        title="No one here yet"
        description="People who join the room will appear here."
      />
    );
  }

  return (
    <ul className="people-list" aria-label="Participants">
      {participants.map((participant) => {
        const isSelf = participant.participant_id === selfParticipantId;
        const isVirtual = participant.kind === "virtual_brse" || participant.is_virtual;
        const participantStatus = isVirtual
          ? brsePeopleCopy.virtual
          : participant.muted_by_host
            ? "Muted by host"
            : formatParticipantStatus(participant.status);
        const canMute =
          isCurrentUserHost &&
          !isSelf &&
          !isVirtual &&
          onMuteParticipant;
        const details = isVirtual
          ? participantStatus
          : [getLanguageLabel(participant.language), participantStatus].join(" · ");

        return (
          <li className="people-row" key={participant.participant_id}>
            <span
              className={isVirtual ? "avatar avatar--ai" : "avatar"}
              aria-hidden="true"
            >
              {getParticipantInitials(participant.display_name, Boolean(isVirtual))}
            </span>

            <div className="people-main">
              <p className="people-name">
                {participant.display_name}
                {isSelf ? <span className="people-you"> (You)</span> : null}
                {participant.is_host ? <Badge>Host</Badge> : null}
              </p>
              <p className="people-details">
                {participant.is_screen_sharing ? (
                  <MonitorUp size={12} aria-label="Sharing screen" />
                ) : null}
                {participant.muted_by_host ? <MicOff size={12} aria-hidden="true" /> : null}
                {details}
              </p>
            </div>

            {canMute ? (
              <Button
                size="sm"
                variant="ghost"
                loading={isMutingParticipant === participant.participant_id}
                onClick={() => onMuteParticipant(participant.participant_id)}
                aria-label={`Mute ${participant.display_name}`}
              >
                Mute
              </Button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function getBrsePeopleCopy({
  brseEnabled,
  brseRoomMode,
  brseAudioExpected,
}: {
  brseEnabled: boolean;
  brseRoomMode: BrseRoomMode;
  brseAudioExpected: boolean;
}) {
  if (!brseEnabled) {
    return {
      virtual: "BRSE relay is off",
    };
  }

  if (brseRoomMode === "text_only" || !brseAudioExpected) {
    return {
      virtual: "BRSE text relay participant",
    };
  }

  if (brseRoomMode === "silent_summary") {
    return {
      virtual: "BRSE summary participant",
    };
  }

  return {
    virtual: "AI voice + text relay participant",
  };
}

function getParticipantInitials(displayName: string, isVirtual: boolean): string {
  if (isVirtual) {
    return "AI";
  }

  const normalized = displayName.trim();
  if (!normalized) {
    return "U";
  }

  const parts = normalized.split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase()).join("") || "U";
}

function formatParticipantStatus(status: ParticipantSnapshot["status"]): string {
  switch (status) {
    case "connected":
      return "In room";
    case "joining":
      return "Joining";
    case "reconnecting":
      return "Reconnecting";
    case "disconnected":
      return "Disconnected";
    default:
      return status;
  }
}
