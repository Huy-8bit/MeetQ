import { useEffect, useRef, useState } from "react";
import { MicOff, MonitorUp, MoreHorizontal } from "lucide-react";
import type { ParticipantSnapshot, RoomPermissions, RoomRole } from "../types/api";
import type { BrseRoomMode } from "../lib/brseModes";
import { getLanguageLabel } from "../lib/languages";
import { normalizeRole, outranks, roleLabel } from "../lib/roomRoles";
import { Badge } from "./ui/Badge";
import { ConfirmDialog } from "./ui/ConfirmDialog";
import { EmptyState } from "./ui/EmptyState";
import { Spinner } from "./ui/Spinner";

interface ParticipantListProps {
  participants: ParticipantSnapshot[];
  selfParticipantId?: string;
  /** Your own role; decides which actions are offered (the server checks them again). */
  selfRole?: RoomRole;
  permissions?: RoomPermissions;
  /** e.g. "remove:pt_123", "role:pt_123" while a request is running. */
  pendingAction?: string | null;
  isMutingParticipant?: string | null;
  onMuteParticipant?: (participantId: string) => void;
  onRemoveParticipant?: (participantId: string) => void;
  onSetRole?: (participantId: string, role: "co_host" | "participant") => void;
  brseEnabled?: boolean;
  brseRoomMode?: BrseRoomMode;
  brseAudioExpected?: boolean;
  embedded?: boolean;
}

interface MenuAction {
  key: string;
  label: string;
  danger?: boolean;
  run: () => void;
}

export function ParticipantList({
  participants,
  selfParticipantId,
  selfRole = "participant",
  permissions,
  pendingAction = null,
  isMutingParticipant = null,
  onMuteParticipant,
  onRemoveParticipant,
  onSetRole,
  brseEnabled = true,
  brseRoomMode = "voice_text",
  brseAudioExpected = true,
}: ParticipantListProps) {
  const [confirmRemove, setConfirmRemove] = useState<ParticipantSnapshot | null>(null);
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

  function actionsFor(participant: ParticipantSnapshot): MenuAction[] {
    const isSelf = participant.participant_id === selfParticipantId;
    const isVirtual = participant.kind === "virtual_brse" || participant.is_virtual;
    const targetRole = participantRole(participant);
    // Room management only goes down the hierarchy and never targets yourself.
    if (isSelf || isVirtual || !permissions || !outranks(selfRole, targetRole)) return [];
    const actions: MenuAction[] = [];
    const id = participant.participant_id;
    if (permissions.can_mute_participant && onMuteParticipant && !participant.muted_by_host) {
      actions.push({ key: "mute", label: "Mute", run: () => onMuteParticipant(id) });
    }
    if (permissions.can_assign_cohost && onSetRole) {
      actions.push(
        targetRole === "co_host"
          ? { key: "demote", label: "Remove co-host", run: () => onSetRole(id, "participant") }
          : { key: "promote", label: "Make co-host", run: () => onSetRole(id, "co_host") },
      );
    }
    if (permissions.can_remove_participant && onRemoveParticipant) {
      actions.push({ key: "remove", label: "Remove from meeting", danger: true, run: () => setConfirmRemove(participant) });
    }
    return actions;
  }

  return (
    <>
      <ul className="people-list" aria-label="Participants">
        {participants.map((participant) => {
          const isSelf = participant.participant_id === selfParticipantId;
          const isVirtual = participant.kind === "virtual_brse" || participant.is_virtual;
          const role = participantRole(participant);
          const label = isVirtual ? null : roleLabel(role);
          const participantStatus = isVirtual
            ? brsePeopleCopy.virtual
            : participant.muted_by_host
              ? "Muted by host"
              : formatParticipantStatus(participant.status);
          const details = isVirtual
            ? participantStatus
            : [getLanguageLabel(participant.language), participantStatus].join(" · ");
          const actions = actionsFor(participant);
          const busy =
            isMutingParticipant === participant.participant_id ||
            pendingAction === `remove:${participant.participant_id}` ||
            pendingAction === `role:${participant.participant_id}`;

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
                  <span className="people-name-text">{participant.display_name}</span>
                  {isSelf ? <span className="people-you"> (You)</span> : null}
                  {label ? <Badge tone={role === "host" ? "accent" : "neutral"}>{label}</Badge> : null}
                </p>
                <p className="people-details">
                  {participant.is_screen_sharing ? (
                    <MonitorUp size={12} aria-label="Sharing screen" />
                  ) : null}
                  {participant.muted_by_host ? <MicOff size={12} aria-hidden="true" /> : null}
                  {details}
                </p>
              </div>

              {busy ? <Spinner /> : actions.length > 0 ? (
                <ParticipantActionsMenu name={participant.display_name} actions={actions} />
              ) : null}
            </li>
          );
        })}
      </ul>

      <ConfirmDialog
        open={confirmRemove !== null}
        title={`Remove ${confirmRemove?.display_name ?? "this person"}?`}
        confirmLabel="Remove"
        tone="danger"
        onCancel={() => setConfirmRemove(null)}
        onConfirm={() => {
          if (confirmRemove) onRemoveParticipant?.(confirmRemove.participant_id);
          setConfirmRemove(null);
        }}
      >
        <p>They&apos;ll leave the meeting right away and can&apos;t rejoin it.</p>
      </ConfirmDialog>
    </>
  );
}

function ParticipantActionsMenu({ name, actions }: { name: string; actions: MenuAction[] }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const firstItemRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return;
    firstItemRef.current?.focus();
    const onPointer = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="people-menu" ref={rootRef}>
      <button
        type="button"
        className="icon-button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Actions for ${name}`}
        title={`Actions for ${name}`}
        onClick={() => setOpen((value) => !value)}
      >
        <MoreHorizontal size={16} aria-hidden="true" />
      </button>
      {open ? (
        <div className="people-menu-popover" role="menu" aria-label={`Actions for ${name}`}>
          {actions.map((action, index) => (
            <button
              key={action.key}
              ref={index === 0 ? firstItemRef : undefined}
              type="button"
              role="menuitem"
              className={action.danger ? "people-menu-item is-danger" : "people-menu-item"}
              onClick={() => {
                setOpen(false);
                action.run();
              }}
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function participantRole(participant: ParticipantSnapshot): RoomRole {
  if (participant.role) return normalizeRole(participant.role);
  return participant.is_host ? "host" : "participant";
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
