import { useEffect, useId, useRef, useState } from "react";
import { Lock, LockOpen, ShieldCheck } from "lucide-react";
import { ApiError } from "../lib/api";
import { hasRoomPasswordErrors, ROOM_PASSWORD_MAX_LENGTH, validateRoomPassword, type RoomPasswordErrors } from "../lib/roomAccess";
import { PERMISSION_DENIED_MESSAGE } from "../lib/roomRoles";
import type { RoomPermissions } from "../types/api";
import { Button } from "./ui/Button";
import { ConfirmDialog } from "./ui/ConfirmDialog";
import { Field } from "./ui/Field";
import { PasswordInput } from "./ui/PasswordInput";

interface RoomSecurityPanelProps {
  passwordRequired: boolean;
  locked: boolean;
  permissions: RoomPermissions;
  pendingAction: string | null;
  disabled?: boolean;
  onSetLocked: (locked: boolean) => void;
  onChangePassword: (password: string) => Promise<void>;
  onRemovePassword: () => void;
}

/**
 * Meeting access and lock. Everyone sees the state; only the host gets the controls
 * (co-hosts don't manage room security). The current password is never shown.
 */
export function RoomSecurityPanel({
  passwordRequired,
  locked,
  permissions,
  pendingAction,
  disabled = false,
  onSetLocked,
  onChangePassword,
  onRemovePassword,
}: RoomSecurityPanelProps) {
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const canManage = permissions.can_manage_password || permissions.can_lock_room;

  if (!canManage) {
    return locked ? (
      <p className="room-security-note text-secondary">
        <Lock size={14} aria-hidden="true" /> This meeting is locked by the host. Nobody new can join.
      </p>
    ) : null;
  }

  return (
    <section className="room-security" aria-labelledby="room-security-title">
      <h3 className="section-title" id="room-security-title">
        <ShieldCheck size={16} aria-hidden="true" /> Room security
      </h3>

      {permissions.can_manage_password ? (
        <div className="room-security-row">
          <div>
            <p className="field-label">Meeting access</p>
            <p className="field-helper">{passwordRequired ? "Password protected" : "Anyone with the link"}</p>
          </div>
          <div className="room-security-actions">
            <Button size="sm" onClick={() => setPasswordOpen(true)} disabled={disabled} loading={pendingAction === "password"}>
              {passwordRequired ? "Change password" : "Set password"}
            </Button>
            {passwordRequired ? (
              <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(true)} disabled={disabled || pendingAction === "password"}>
                Remove password
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {permissions.can_lock_room ? (
        <div className="room-security-row">
          <div>
            <p className="field-label">Meeting lock</p>
            <p className="field-helper">
              {locked ? "Locked — people already here stay, nobody new can join" : "Unlocked"}
            </p>
          </div>
          <Button
            size="sm"
            icon={locked ? <LockOpen size={14} aria-hidden="true" /> : <Lock size={14} aria-hidden="true" />}
            onClick={() => onSetLocked(!locked)}
            disabled={disabled}
            loading={pendingAction === "lock"}
          >
            {locked ? "Unlock meeting" : "Lock meeting"}
          </Button>
        </div>
      ) : null}

      <ChangePasswordDialog
        open={passwordOpen}
        isChange={passwordRequired}
        onClose={() => setPasswordOpen(false)}
        onSubmit={onChangePassword}
      />
      <ConfirmDialog
        open={confirmRemove}
        title="Remove the meeting password?"
        confirmLabel="Remove password"
        tone="danger"
        onCancel={() => setConfirmRemove(false)}
        onConfirm={() => {
          setConfirmRemove(false);
          onRemovePassword();
        }}
      >
        <p>Anyone with the link will be able to join. People already in the meeting aren&apos;t affected.</p>
      </ConfirmDialog>
    </section>
  );
}

function ChangePasswordDialog({
  open,
  isChange,
  onClose,
  onSubmit,
}: {
  open: boolean;
  isChange: boolean;
  onClose: () => void;
  onSubmit: (password: string) => Promise<void>;
}) {
  const titleId = useId();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<RoomPasswordErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    // Fresh, empty fields every time: the current password is never shown or kept.
    setPassword("");
    setConfirm("");
    setErrors({});
    setSubmitError(null);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const next = validateRoomPassword(password, confirm);
    setErrors(next);
    if (hasRoomPasswordErrors(next)) return;
    setSaving(true);
    setSubmitError(null);
    try {
      await onSubmit(password);
      onClose();
    } catch (error) {
      setSubmitError(
        error instanceof ApiError && error.status === 403
          ? PERMISSION_DENIED_MESSAGE
          : error instanceof ApiError && error.status === 422
            ? error.message
            : "Couldn't update the password. Try again.",
      );
    } finally {
      setSaving(false);
      setPassword("");
      setConfirm("");
    }
  }

  return (
    <div className="dialog-layer">
      <div className="dialog-backdrop" onClick={() => !saving && onClose()} aria-hidden="true" />
      <form className="dialog card" role="dialog" aria-modal="true" aria-labelledby={titleId} onSubmit={handleSubmit}>
        <div className="card-body dialog-body">
          <h2 className="card-title" id={titleId}>
            {isChange ? "Change meeting password" : "Set a meeting password"}
          </h2>
          <p className="dialog-text">
            New people will need it to join. People already in the meeting stay. Share it separately from the link.
          </p>
          <Field label="New password" htmlFor="room-new-password" error={errors.password} helper="At least 6 characters.">
            <PasswordInput
              id="room-new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
              maxLength={ROOM_PASSWORD_MAX_LENGTH}
              autoFocus
              aria-invalid={errors.password ? true : undefined}
            />
          </Field>
          <Field label="Confirm password" htmlFor="room-new-password-confirm" error={errors.confirm}>
            <PasswordInput
              id="room-new-password-confirm"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              autoComplete="new-password"
              maxLength={ROOM_PASSWORD_MAX_LENGTH}
              aria-invalid={errors.confirm ? true : undefined}
            />
          </Field>
          {submitError ? <p className="field-error" role="alert">{submitError}</p> : null}
          <div className="dialog-actions">
            <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={saving}>
              Save password
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}
