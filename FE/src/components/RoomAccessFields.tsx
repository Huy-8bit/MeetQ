import { Field } from "./ui/Field";
import { PasswordInput } from "./ui/PasswordInput";
import { SegmentedControl } from "./ui/SegmentedControl";
import {
  ROOM_ACCESS_OPTIONS,
  ROOM_PASSWORD_MAX_LENGTH,
  type RoomPasswordErrors,
} from "../lib/roomAccess";
import type { RoomAccess } from "../types/api";

interface RoomAccessFieldsProps {
  access: RoomAccess;
  password: string;
  confirm: string;
  errors: RoomPasswordErrors;
  disabled?: boolean;
  onAccessChange: (access: RoomAccess) => void;
  onPasswordChange: (password: string) => void;
  onConfirmChange: (confirm: string) => void;
}

export function RoomAccessFields({
  access,
  password,
  confirm,
  errors,
  disabled = false,
  onAccessChange,
  onPasswordChange,
  onConfirmChange,
}: RoomAccessFieldsProps) {
  return (
    <>
      <Field
        asGroup
        labelId="room-access-label"
        label="Room access"
        helper={ROOM_ACCESS_OPTIONS.find((option) => option.value === access)?.detail}
      >
        <SegmentedControl
          ariaLabelledBy="room-access-label"
          value={access}
          onChange={onAccessChange}
          disabled={disabled}
          options={ROOM_ACCESS_OPTIONS.map((option) => ({ value: option.value, label: option.label }))}
        />
      </Field>

      {access === "password" ? (
        <div className="room-access-passwords">
          <Field
            label="Password"
            htmlFor="room-password"
            error={errors.password}
            helper="At least 6 characters. Share it separately from the link."
          >
            <PasswordInput
              id="room-password"
              name="room-password"
              value={password}
              onChange={(event) => onPasswordChange(event.target.value)}
              autoComplete="new-password"
              maxLength={ROOM_PASSWORD_MAX_LENGTH}
              disabled={disabled}
              aria-invalid={errors.password ? true : undefined}
            />
          </Field>
          <Field label="Confirm password" htmlFor="room-password-confirm" error={errors.confirm}>
            <PasswordInput
              id="room-password-confirm"
              name="room-password-confirm"
              value={confirm}
              onChange={(event) => onConfirmChange(event.target.value)}
              autoComplete="new-password"
              maxLength={ROOM_PASSWORD_MAX_LENGTH}
              disabled={disabled}
              aria-invalid={errors.confirm ? true : undefined}
            />
          </Field>
        </div>
      ) : null}
    </>
  );
}
