import type { ChatTranslationMode, Language } from "../types/api";
import type {
  ClientMessage,
  ServerEvent,
  WsEnvelope,
} from "../types/ws";
import { resolveGatewayWebSocketUrl } from "./urls";

const PING_INTERVAL_MS = 15000;
const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000];
const REGISTRY_RELEASE_DELAY_MS = 0;

type GatewaySocketState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected";

export interface GatewaySocketCallbacks {
  onEvent: (event: ServerEvent) => void;
  onStateChange?: (state: GatewaySocketState) => void;
  onFatalClose?: (code: number, reason: string) => void;
}

export class GatewaySocketCancelledError extends Error {
  constructor(message = "Gateway socket connection was cancelled.") {
    super(message);
    this.name = "GatewaySocketCancelledError";
  }
}

export class GatewaySocket {
  private readonly roomId: string;
  private readonly url: string;
  private readonly subscribers = new Set<GatewaySocketCallbacks>();
  private socket: WebSocket | null = null;
  private pingTimer: number | null = null;
  private reconnectTimer: number | null = null;
  private reconnectAttempt = 0;
  private intentionalClose = false;
  private hasConnectedOnce = false;
  private state: GatewaySocketState = "disconnected";
  private connectPromise: Promise<void> | null = null;
  private resolveConnect: (() => void) | null = null;
  private rejectConnect: ((error: Error) => void) | null = null;

  constructor(rawUrl: string, roomId: string) {
    this.roomId = roomId;
    this.url = resolveGatewayWebSocketUrl(rawUrl);
  }

  subscribe(
    callbacks: GatewaySocketCallbacks,
    options: { emitCurrentState?: boolean } = {},
  ): () => void {
    this.subscribers.add(callbacks);
    if (options.emitCurrentState !== false) {
      callbacks.onStateChange?.(this.state);
    }

    return () => {
      this.subscribers.delete(callbacks);
    };
  }

  getState(): GatewaySocketState {
    return this.state;
  }

  connect(): Promise<void> {
    if (this.socket?.readyState === WebSocket.OPEN) {
      if (this.state !== "connected") {
        this.setState("connected");
      }
      return Promise.resolve();
    }

    if (this.connectPromise) {
      return this.connectPromise;
    }

    if (this.socket?.readyState === WebSocket.CONNECTING) {
      return this.waitForConnectionResolution();
    }

    if (this.state === "reconnecting") {
      return this.waitForConnectionResolution();
    }

    this.intentionalClose = false;
    this.connectPromise = new Promise<void>((resolve, reject) => {
      this.resolveConnect = resolve;
      this.rejectConnect = reject;
      this.openSocket(false);
    });

    return this.connectPromise;
  }

  disconnect(reason = "Client leave"): void {
    this.intentionalClose = true;
    this.clearTimers();
    this.rejectPendingConnect(new GatewaySocketCancelledError());
    this.setState("disconnected");

    if (this.socket) {
      const socket = this.socket;
      this.socket = null;
      if (
        socket.readyState === WebSocket.OPEN ||
        socket.readyState === WebSocket.CONNECTING
      ) {
        socket.close(1000, reason);
      }
    }
  }

  disconnectForUnload(reason = "Client unload"): void {
    this.intentionalClose = true;
    this.clearTimers();
    this.rejectPendingConnect(new GatewaySocketCancelledError());
    this.setState("disconnected");

    if (!this.socket) {
      return;
    }

    const socket = this.socket;
    this.socket = null;
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
      socket.close(1001, reason);
    }
  }

  ping(): void {
    this.sendEnvelope("ping", {
      client_time: new Date().toISOString(),
    });
  }

  setLanguage(language: Language): void {
    this.sendEnvelope("set_language", {
      language,
    });
  }

  sendScreenShareStart(payload: {
    track_sid?: string;
    track_name?: string;
    source?: "screen_share";
  }): void {
    this.sendEnvelope("screen_share.start", payload);
  }

  sendScreenShareStop(): void {
    this.sendEnvelope("screen_share.stop", {});
  }

  enableBrse(): void {
    this.sendEnvelope("room.brse.enable", {});
  }

  disableBrse(): void {
    this.sendEnvelope("room.brse.disable", {});
  }

  sendChatMessage(text: string, translationMode?: ChatTranslationMode): string {
    return this.sendEnvelope("chat.send", {
      text,
      ...(translationMode ? { translation_mode: translationMode } : {}),
    });
  }

  sendMuteParticipant(targetParticipantId: string): void {
    this.sendEnvelope("moderation.mute_participant", {
      target_participant_id: targetParticipantId,
    });
  }

  private openSocket(isReconnect: boolean): void {
    this.clearReconnectTimer();
    this.setState(isReconnect ? "reconnecting" : "connecting");

    const socket = new WebSocket(this.url);
    this.socket = socket;

    socket.addEventListener("open", () => {
      if (this.socket !== socket) {
        socket.close(1000, "Superseded connection");
        return;
      }

      this.hasConnectedOnce = true;
      this.reconnectAttempt = 0;
      this.startPingLoop();
      this.setState("connected");
      this.resolveConnect?.();
      this.resolveConnect = null;
      this.rejectConnect = null;
      this.connectPromise = null;
    });

    socket.addEventListener("message", (event) => {
      if (this.socket !== socket) {
        return;
      }

      try {
        const payload = JSON.parse(event.data) as ServerEvent;
        this.subscribers.forEach((subscriber) => {
          subscriber.onEvent(payload);
        });
      } catch (error) {
        console.error("Failed to parse gateway event", error);
      }
    });

    socket.addEventListener("close", (event) => {
      this.stopPingLoop();

      if (this.socket === socket) {
        this.socket = null;
      }

      if (this.intentionalClose) {
        return;
      }

      if (isFatalCloseCode(event.code)) {
        this.setState("disconnected");
        this.rejectPendingConnect(
          new Error(event.reason || `Gateway socket closed with code ${event.code}`),
        );
        this.subscribers.forEach((subscriber) => {
          subscriber.onFatalClose?.(event.code, event.reason);
        });
        return;
      }

      if (!this.hasConnectedOnce) {
        this.setState("disconnected");
        this.rejectPendingConnect(
          new Error(event.reason || "Gateway socket closed before becoming ready."),
        );
        return;
      }

      this.scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      if (!isReconnect && this.connectPromise) {
        this.setState("connecting");
      }
    });
  }

  private sendEnvelope<TType extends ClientMessage["type"], TPayload>(
    type: TType,
    payload: TPayload,
  ): string {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error("Gateway socket is not connected");
    }

    const message: WsEnvelope<TType, TPayload> = {
      type,
      event_id: buildClientEventId(),
      room_id: this.roomId,
      sent_at: new Date().toISOString(),
      payload,
    };

    this.socket.send(JSON.stringify(message));
    return message.event_id;
  }

  private scheduleReconnect(): void {
    if (this.intentionalClose || !this.hasConnectedOnce) {
      this.setState("disconnected");
      return;
    }

    this.stopPingLoop();
    this.setState("reconnecting");

    const delay =
      RECONNECT_DELAYS_MS[
        Math.min(this.reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)
      ];
    this.reconnectAttempt += 1;

    this.reconnectTimer = window.setTimeout(() => {
      this.openSocket(true);
    }, delay);
  }

  private startPingLoop(): void {
    this.stopPingLoop();
    this.pingTimer = window.setInterval(() => {
      try {
        this.ping();
      } catch {
        this.stopPingLoop();
      }
    }, PING_INTERVAL_MS);
  }

  private stopPingLoop(): void {
    if (this.pingTimer !== null) {
      window.clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private clearTimers(): void {
    this.stopPingLoop();
    this.clearReconnectTimer();
  }

  private rejectPendingConnect(error: Error): void {
    this.rejectConnect?.(error);
    this.resolveConnect = null;
    this.rejectConnect = null;
    this.connectPromise = null;
  }

  private setState(nextState: GatewaySocketState): void {
    if (this.state === nextState) {
      return;
    }

    this.state = nextState;
    this.subscribers.forEach((subscriber) => {
      subscriber.onStateChange?.(nextState);
    });
  }

  private waitForConnectionResolution(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const unsubscribe = this.subscribe({
        onEvent: () => undefined,
        onStateChange: (state) => {
          if (state === "connected") {
            unsubscribe();
            resolve();
            return;
          }

          if (state === "disconnected") {
            unsubscribe();
            reject(
              new Error("Gateway socket became disconnected before it was ready."),
            );
          }
        },
      }, { emitCurrentState: false });

      if (this.state === "connected") {
        unsubscribe();
        resolve();
      } else if (this.state === "disconnected") {
        unsubscribe();
        reject(
          new Error("Gateway socket became disconnected before it was ready."),
        );
      }
    });
  }
}

interface SharedGatewaySocketEntry {
  retainCount: number;
  releaseTimer: number | null;
  socket: GatewaySocket;
}

const gatewaySocketRegistry = new Map<string, SharedGatewaySocketEntry>();

export function retainGatewaySocket(config: {
  roomId: string;
  sessionKey: string;
  websocketUrl: string;
}): GatewaySocket {
  let entry = gatewaySocketRegistry.get(config.sessionKey);
  if (!entry) {
    entry = {
      retainCount: 0,
      releaseTimer: null,
      socket: new GatewaySocket(config.websocketUrl, config.roomId),
    };
    gatewaySocketRegistry.set(config.sessionKey, entry);
  }

  entry.retainCount += 1;
  if (entry.releaseTimer !== null) {
    window.clearTimeout(entry.releaseTimer);
    entry.releaseTimer = null;
  }

  return entry.socket;
}

export function releaseGatewaySocket(sessionKey: string): void {
  const entry = gatewaySocketRegistry.get(sessionKey);
  if (!entry) {
    return;
  }

  entry.retainCount = Math.max(0, entry.retainCount - 1);
  if (entry.retainCount > 0 || entry.releaseTimer !== null) {
    return;
  }

  entry.releaseTimer = window.setTimeout(() => {
    const current = gatewaySocketRegistry.get(sessionKey);
    if (!current || current.retainCount > 0) {
      return;
    }

    current.socket.disconnect("Session released");
    gatewaySocketRegistry.delete(sessionKey);
  }, REGISTRY_RELEASE_DELAY_MS);
}

function buildClientEventId(): string {
  return `evt_${Math.random().toString(36).slice(2, 14)}`;
}

function isFatalCloseCode(code: number): boolean {
  return code === 4401 || code === 4403 || code === 4404 || code === 4410;
}
