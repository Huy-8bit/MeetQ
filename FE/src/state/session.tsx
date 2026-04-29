import {
  createContext,
  useContext,
  useState,
  type PropsWithChildren,
} from "react";
import type { JoinRoomResponse } from "../types/api";

export interface RoomSession {
  sessionKey: string;
  roomId: string;
  roomToken: string;
  roomTokenExpiresAt: string;
  websocketUrl: string;
  livekit: JoinRoomResponse["livekit"];
  participant: JoinRoomResponse["participant"];
  room: JoinRoomResponse["room"];
  snapshot: JoinRoomResponse["snapshot"];
}

interface SessionContextValue {
  getSession: (roomId: string) => RoomSession | null;
  saveSession: (join: JoinRoomResponse) => RoomSession;
  clearSession: (roomId: string) => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function buildRoomSessionKey(input: {
  roomId: string;
  participantId: string;
  sessionId: string;
  websocketUrl: string;
}): string {
  return [
    input.roomId,
    input.participantId,
    input.sessionId,
    input.websocketUrl,
  ].join("::");
}

export function SessionProvider({ children }: PropsWithChildren) {
  const [sessions, setSessions] = useState<Record<string, RoomSession>>({});
  const value: SessionContextValue = {
    getSession(roomId) {
      return sessions[roomId] ?? null;
    },

    saveSession(join) {
      const session: RoomSession = {
        sessionKey: buildRoomSessionKey({
          roomId: join.room.room_id,
          participantId: join.participant.participant_id,
          sessionId: join.participant.session_id,
          websocketUrl: join.websocket.url,
        }),
        roomId: join.room.room_id,
        roomToken: join.room_token.token,
        roomTokenExpiresAt: join.room_token.expires_at,
        websocketUrl: join.websocket.url,
        livekit: join.livekit,
        participant: join.participant,
        room: join.room,
        snapshot: join.snapshot,
      };

      setSessions((current) => ({
        ...current,
        [session.roomId]: session,
      }));

      return session;
    },

    clearSession(roomId) {
      setSessions((current) => {
        if (!(roomId in current)) {
          return current;
        }

        const next = { ...current };
        delete next[roomId];
        return next;
      });
    },
  };

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSessionStore() {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSessionStore must be used within SessionProvider");
  }
  return context;
}
