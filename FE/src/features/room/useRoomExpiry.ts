import { useEffect, useRef, useState } from "react";

export interface RoomExpiryState {
  isExpired: boolean;
  remainingMs: number;
  remainingLabel: string;
}

function computeExpiry(expiresAt: string | null | undefined): RoomExpiryState {
  if (!expiresAt) {
    return { isExpired: false, remainingMs: Infinity, remainingLabel: "" };
  }

  const remaining = new Date(expiresAt).getTime() - Date.now();

  if (remaining <= 0) {
    return { isExpired: true, remainingMs: 0, remainingLabel: "Expired" };
  }

  const totalSeconds = Math.ceil(remaining / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  let label: string;
  if (totalSeconds > 600) {
    label = `${minutes}m`;
  } else {
    label = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }

  return { isExpired: false, remainingMs: remaining, remainingLabel: label };
}

export function useRoomExpiry(expiresAt: string | null | undefined): RoomExpiryState {
  const [state, setState] = useState<RoomExpiryState>(() => computeExpiry(expiresAt));
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    if (!expiresAt) {
      setState({ isExpired: false, remainingMs: Infinity, remainingLabel: "" });
      return;
    }

    const tick = () => {
      const next = computeExpiry(expiresAt);
      setState(next);
      if (next.isExpired && intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };

    tick();
    intervalRef.current = setInterval(tick, 1000);

    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [expiresAt]);

  return state;
}

export function formatExpiresAtHuman(expiresAt: string | null | undefined): string {
  if (!expiresAt) return "";
  const d = new Date(expiresAt);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
