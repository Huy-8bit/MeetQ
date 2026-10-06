import type { MeetingLanguage, RoomPermissionName, RoomPermissions, RoomRole } from "../types/api";
import { formatMeetingLanguageBridge } from "./languages";

/**
 * Mirror of the server's permission matrix (BE server/service/gateway/room_permissions.py),
 * used only to decide what to render. The server checks every action again; a hidden
 * button is a convenience, never the protection.
 */
const CO_HOST: RoomPermissionName[] = [
  "can_manage_ai",
  "can_manage_recording",
  "can_mute_participant",
  "can_remove_participant",
];
const ALL: RoomPermissionName[] = [
  ...CO_HOST,
  "can_manage_room_security",
  "can_assign_cohost",
  "can_manage_password",
  "can_lock_room",
  "can_extend_room",
];
const RANK: Record<RoomRole, number> = { host: 3, co_host: 2, participant: 1 };

export const PERMISSION_DENIED_MESSAGE = "You don't have permission to perform this action.";

export function normalizeRole(role: string | null | undefined): RoomRole {
  return role === "host" || role === "co_host" ? role : "participant";
}

export function permissionsFor(role: RoomRole, enforced = true): RoomPermissions {
  const granted = !enforced ? ["can_manage_ai", "can_manage_recording"] : role === "host" ? ALL : role === "co_host" ? CO_HOST : [];
  return Object.fromEntries(ALL.map((name) => [name, granted.includes(name)])) as RoomPermissions;
}

/** Targeted actions (mute, remove) only go down: host → co-host/participant, co-host → participant. */
export function outranks(actor: RoomRole, target: RoomRole): boolean {
  return RANK[actor] > RANK[target];
}

export function roleLabel(role: RoomRole | null | undefined): string | null {
  if (role === "host") return "Host";
  if (role === "co_host") return "Co-host";
  return null;
}

/** Title, or a fallback built from the room languages ("Vietnamese ⇄ Japanese meeting"). */
export function formatMeetingTitle(title: string | null | undefined, languages: readonly string[] | null | undefined): string {
  const trimmed = title?.trim();
  if (trimmed) return trimmed;
  if (!languages || languages.length === 0) return "Meeting";
  return `${formatMeetingLanguageBridge(languages as MeetingLanguage[])} meeting`;
}
