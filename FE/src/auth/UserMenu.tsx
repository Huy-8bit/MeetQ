import { useEffect, useId, useRef, useState } from "react";
import { LogOut } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./AuthProvider";
import type { AuthUser } from "./types";

function initials(user: AuthUser): string {
  const source = user.name || user.email;
  const parts = source.split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? `${parts[0][0]}${parts[parts.length - 1][0]}` : source.slice(0, 2);
  return letters.toUpperCase();
}

export function UserAvatar({ user, size = 32 }: { user: AuthUser; size?: number }) {
  const [broken, setBroken] = useState(false);
  if (user.avatarUrl && !broken) {
    return (
      <img
        className="user-avatar"
        src={user.avatarUrl}
        alt=""
        width={size}
        height={size}
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
      />
    );
  }
  return (
    <span className="user-avatar user-avatar--initials" style={{ width: size, height: size }} aria-hidden="true">
      {initials(user)}
    </span>
  );
}

/** Avatar button with name, email and Sign out (user realm only). */
export function UserMenu() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!user) return null;

  async function handleSignOut() {
    setSigningOut(true);
    await signOut();
    navigate("/login", { replace: true });
  }

  return (
    <div className="user-menu" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="user-menu-trigger"
        aria-label={`Account: ${user.name}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <UserAvatar user={user} />
      </button>
      {open ? (
        <div className="user-menu-popover" id={menuId} role="menu" aria-label="Account">
          <div className="user-menu-identity">
            <UserAvatar user={user} size={40} />
            <div className="user-menu-text">
              <span className="user-menu-name">{user.name}</span>
              <span className="user-menu-email">{user.email}</span>
            </div>
          </div>
          <button
            type="button"
            role="menuitem"
            className="user-menu-item"
            onClick={() => void handleSignOut()}
            disabled={signingOut}
            autoFocus
          >
            <LogOut size={16} aria-hidden="true" />
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
