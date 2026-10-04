import type { RoomAccess } from "../types/api";

export const ROOM_PASSWORD_MIN_LENGTH = 6;
export const ROOM_PASSWORD_MAX_LENGTH = 128;

export const ROOM_ACCESS_OPTIONS: Array<{ value: RoomAccess; label: string; detail: string }> = [
  {
    value: "link",
    label: "Anyone with the link",
    detail: "Anyone who has the room link can join.",
  },
  {
    value: "password",
    label: "Require a password",
    detail: "People need the link and the password to join.",
  },
];

export interface RoomPasswordErrors {
  password?: string;
  confirm?: string;
}

/** Length only (6–128). No composition rules — any characters are allowed. */
export function validateRoomPassword(password: string, confirm: string): RoomPasswordErrors {
  const errors: RoomPasswordErrors = {};
  if (password.length < ROOM_PASSWORD_MIN_LENGTH) {
    errors.password = `Password must be at least ${ROOM_PASSWORD_MIN_LENGTH} characters.`;
  } else if (password.length > ROOM_PASSWORD_MAX_LENGTH) {
    errors.password = `Password must be at most ${ROOM_PASSWORD_MAX_LENGTH} characters.`;
  }
  if (!errors.password && confirm !== password) {
    errors.confirm = "Passwords don't match.";
  }
  return errors;
}

export function hasRoomPasswordErrors(errors: RoomPasswordErrors): boolean {
  return Boolean(errors.password || errors.confirm);
}
